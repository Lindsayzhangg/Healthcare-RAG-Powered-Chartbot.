import os
from langchain_openai import ChatOpenAI
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain import hub
from langchain_pinecone import PineconeVectorStore
from langchain.memory import ConversationBufferMemory
from langchain_voyageai import VoyageAIEmbeddings
from langchain.chains import create_history_aware_retriever
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import os
from dotenv import load_dotenv
import uuid
import boto3

# Setup
load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
os.environ["VOYAGE_AI_API_KEY"] = os.getenv("VOYAGE_AI_API_KEY")
os.environ["PINECONE_API_KEY"] = os.getenv("PINECONE_API_KEY")

# Pull the retrieval QA chat prompt
retrieval_qa_chat_prompt = hub.pull("langchain-ai/retrieval-qa-chat")
llm = ChatOpenAI()

# Initialize the retriever using PineconeVectorStore
model_name = "voyage-large-2"
embedding_function = VoyageAIEmbeddings(
    model=model_name,
    voyage_api_key=os.environ["VOYAGE_AI_API_KEY"]
)
vector_store = PineconeVectorStore.from_existing_index(
    embedding=embedding_function,
    index_name="test"
)
retriever = vector_store.as_retriever()

# Create the combined documents chain
# combine_docs_chain = create_stuff_documents_chain(
#     llm, retrieval_qa_chat_prompt
# )

# CODE DIRECTLY FROM LANGCHAIN DOCUMENTATION
contextualize_q_system_prompt = (
    "Given a chat history and the latest user question "
    "which might reference context in the chat history, "
    "formulate a standalone question which can be understood "
    "without the chat history. Do NOT answer the question, "
    "just reformulate it if needed and otherwise return it as is."
)

contextualize_q_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)

history_aware_retriever = create_history_aware_retriever(
    llm, retriever, contextualize_q_prompt
)

# ADDED
system_prompt = (
    "You are an assistant for question-answering tasks. "
    "Use the following pieces of retrieved context to answer "
    "the question. If you don't know the answer, say that you "
    "don't know. Use three sentences maximum and keep the "
    "answer concise."
    "\n\n"
    "{context}"
)

qa_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)

question_answer_chain = create_stuff_documents_chain(llm, retrieval_qa_chat_prompt)

rag_retreival_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

# Initialize memory
memory = ConversationBufferMemory()

# Create the retrieval chain
# retrieval_chain = create_retrieval_chain(retriever, combine_docs_chain)

# CODE DIRECTLY FROM LANGCHAIN DOCUMENTATION
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory

store = {}

def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

conversational_rag_chain = RunnableWithMessageHistory(
    rag_retreival_chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
    output_messages_key="answer",
)

def chat():
    print("Start chatting with the bot (type 'exit' to stop):")
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'exit':
            print("Ending the conversation. Goodbye!")
            break
        # response = retrieval_chain.invoke({"input": user_input})["answer"]
        response = conversational_rag_chain.invoke({"input": user_input}, config={"configurable": {"session_id": "test"}})["answer"]
        print("Bot:", response)

# ADDED: Functions to save chat history and upload to S3
def save_chat_history_to_file(filename, history):
    with open(filename, 'w') as file:
        file.write(history)

def upload_file_to_s3(s3_client, bucket, key, filename):
    s3_client.upload_file(filename, bucket, key)

def chat():
    print("Start chatting with the bot (type 'exit' to stop):")
    session_id = str(uuid.uuid4())
    s3_client = boto3.client("s3")
    bucket_name = "chat-history-process"
    chat_history_key = f"raw-data/chat_history_{session_id}.txt"
    chat_history = f"\nSession ID: {session_id}\n"
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'exit':
            print("Ending the conversation. Goodbye!")
            break
        response = conversational_rag_chain.invoke({"input": user_input}, config={"configurable": {"session_id": "test"}})["answer"]
        print("Bot:", response)
        
        # Append interaction to chat history
        chat_history += f"You: {user_input}\nAI: {response}\n"
    
    # Save the chat history to a file
    local_filename = f"./history/chat_history_{session_id}.txt"
    save_chat_history_to_file(local_filename, chat_history)

    # Upload the file to S3
    upload_file_to_s3(s3_client, bucket_name, chat_history_key, local_filename)
    print(f"Chat history saved and uploaded to S3 as '{chat_history_key}' in bucket '{bucket_name}'")


# Start the chat
chat()
