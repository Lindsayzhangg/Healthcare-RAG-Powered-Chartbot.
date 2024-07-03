import os
from dotenv import load_dotenv
import numpy as np
import pandas as pd
import nltk
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from rouge import Rouge
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain import hub
from langchain_pinecone import PineconeVectorStore
from langchain.memory import ConversationBufferMemory
from langchain_voyageai import VoyageAIEmbeddings
from langchain.chains import create_history_aware_retriever
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from ragas.metrics import context_relevancy, answer_relevancy, faithfulness, context_recall, answer_correctness
from ragas.metrics.critique import harmfulness
from ragas import evaluate
from datasets import Dataset
import warnings

# Ignore all warnings
warnings.filterwarnings("ignore")

# Setup
load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
os.environ["VOYAGE_AI_API_KEY"] = os.getenv("VOYAGE_AI_API_KEY")
os.environ["PINECONE_API_KEY"] = os.getenv("PINECONE_API_KEY")
os.environ["GROQ_API_KEY"] = os.getenv("GROQ_API_KEY")

# Functions
def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def bleu_score(reference, hypothesis):
    reference_tokens = [nltk.word_tokenize(reference)]
    hypothesis_tokens = nltk.word_tokenize(hypothesis)
    smoothing_function = SmoothingFunction().method1
    return sentence_bleu(reference_tokens, hypothesis_tokens, smoothing_function=smoothing_function)

def edit_distance(reference, hypothesis):
    m = len(reference) + 1
    n = len(hypothesis) + 1

    # Create a matrix to store the distances
    dp = np.zeros((m, n), dtype=int)

    # Initialize the first row and column
    for i in range(m):
        dp[i][0] = i
    for j in range(n):
        dp[0][j] = j

    # Compute the edit distance
    for i in range(1, m):
        for j in range(1, n):
            cost = 0 if reference[i-1] == hypothesis[j-1] else 1
            dp[i][j] = min(dp[i-1][j] + 1,        # Deletion
                           dp[i][j-1] + 1,        # Insertion
                           dp[i-1][j-1] + cost)   # Substitution

    return dp[m-1][n-1]

# Pull the retrieval QA chat prompt
retrieval_qa_chat_prompt = hub.pull("langchain-ai/retrieval-qa-chat")

# Define LLMs - inference and ground truth
inference_llm = ChatGroq(model_name="llama3-8b-8192")
# inference_llm = ChatOpenAI(model="gpt-3.5-turbo")
# inference_llm = ChatOpenAI(model="gpt-4o")
groundtruth_llm = ChatOpenAI(model="gpt-4o")

# Initialize the retriever using PineconeVectorStore
## Embeddings HAVE to be VOYAGE because Pinecone dataset was ingested using VOYAGE
model_name = "voyage-large-2"
embedding_function = VoyageAIEmbeddings(
    model=model_name,
    voyage_api_key=os.environ["VOYAGE_AI_API_KEY"]
)
vector_store = PineconeVectorStore.from_existing_index(
    embedding=embedding_function,
    index_name="drugbank"
)
retriever = vector_store.as_retriever()

# CODE DIRECTLY FROM LANGCHAIN DOCUMENTATION
# contextualize_q_system_prompt = (
#     "Given a chat history and the latest user question "
#     "which might reference context in the chat history, "
#     "formulate a standalone question which can be understood "
#     "without the chat history. Do NOT answer the question, "
#     "just reformulate it if needed and otherwise return it as is."
#     "Be concise, answer the question in a couple of sentences."
# )
contextualize_q_system_prompt = (
    "Given a chat history and the latest user question which might reference context in the chat history, "
    "answer the question based on the given context, in the topic of patient education."
    "Answer concisely, in no more than 3 sentences, unless the user asks for more details." 
    "Try to reference the given context in the chat history as much as possible to ensure accuracy."
)
contextualize_q_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)

# The retriever and chain below makes up the rag_retreival_chain, create 2 versions of it
## INFERENCE - GENERATED ANSWER
inf_history_aware_retriever = create_history_aware_retriever(
    inference_llm, retriever, contextualize_q_prompt
)
inf_question_answer_chain = create_stuff_documents_chain(inference_llm, retrieval_qa_chat_prompt)
inf_rag_retreival_chain = create_retrieval_chain(inf_history_aware_retriever, inf_question_answer_chain)
## GROUND TRUTH
gt_history_aware_retriever = create_history_aware_retriever(
    groundtruth_llm, retriever, contextualize_q_prompt
)
gt_question_answer_chain = create_stuff_documents_chain(groundtruth_llm, retrieval_qa_chat_prompt)
gt_rag_retreival_chain = create_retrieval_chain(gt_history_aware_retriever, gt_question_answer_chain)

# Initialize memory
memory = ConversationBufferMemory()
store = {}

inf_conversational_rag_chain = RunnableWithMessageHistory(
    inf_rag_retreival_chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
    output_messages_key="answer",
)
gt_conversational_rag_chain = RunnableWithMessageHistory(
    gt_rag_retreival_chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
    output_messages_key="answer",
)

def chat():
    conversation_data = []
    print("Start chatting with the bot (type 'exit' to stop):")
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'exit':
            print("Ending the conversation. Goodbye!")
            break
        # Make sure that you specify a different session id
        inf_result = inf_conversational_rag_chain.invoke({"input": user_input}, config={"configurable": {"session_id": "inference"}})
        gt_result = gt_conversational_rag_chain.invoke({"input": user_input}, config={"configurable": {"session_id": "ground_truth"}})
        inf_response = inf_result["answer"]
        gt_response = gt_result["answer"]
        inf_retrieved_context = inf_result.get("context", "Nothing")
        gt_retrieved_context = gt_result.get("context", "Nothing")
        # Extract text content from Document objects
        inf_context_text = [doc.page_content for doc in inf_retrieved_context]
        # Collect conversation data
        conversation_data.append({
            "input": user_input,
            "inf_response": inf_response,
            "gt_response": gt_response,
            "inf_context": inf_context_text,
        })
        # Prepare data for evaluation
        eval_data = {
            # "question": [d["input"] for d in conversation_data],
            "question": user_input,
            "contexts": [d["inf_context"] for d in conversation_data],
            "answer": [d["inf_response"] for d in conversation_data],
            "ground_truth": [d["gt_response"] for d in conversation_data]
        }
        # Create a Dataset for evaluation
        dataset_eval = Dataset.from_pandas(pd.DataFrame(eval_data))

        # Evaluate the conversation data
        result = evaluate(
            dataset_eval,
            metrics=[
                context_relevancy,
                faithfulness,
                answer_relevancy,
                context_recall,
                harmfulness,
                answer_correctness
            ],
        )
        eval_df = result.to_pandas()
        # Retrieved context
        print("Inference bot:", inf_response)
        print("-------------------------------------------------------------------")
        print("Ground-truth bot:", gt_response)
        # Print eval score
        print("BLEU score:", round(bleu_score(gt_response, inf_response), 6))
        print("Edit distance:", edit_distance(gt_response, inf_response))
        # context_relevancy	faithfulness	answer_relevancy	context_recall	harmfulness
        print("Context relevancy:", round(eval_df.context_relevancy.loc[0], 6))
        print("Faithfulness:", eval_df.faithfulness.loc[0])
        print("Answer relevancy:", round(eval_df.answer_relevancy.loc[0], 6))
        print("Answer correctness:", eval_df.answer_correctness.loc[0])
        print("Context recall:", round(eval_df.context_recall.loc[0], 6))
        print("Harmfulness:", round(eval_df.harmfulness.loc[0], 6))

# Start the chat
chat()