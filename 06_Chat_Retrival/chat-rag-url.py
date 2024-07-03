from langchain_voyageai import VoyageAIEmbeddings
import os
import boto3
from urllib.parse import urlparse
from pinecone import Pinecone
from langchain_openai import ChatOpenAI
import openai
from langchain.chains import LLMChain, RetrievalQA
import time
import re
from langchain_pinecone import PineconeVectorStore
from langchain.memory import ConversationBufferMemory
from langchain.schema import HumanMessage
from langchain.prompts import ChatPromptTemplate
from langchain.chains import ConversationChain
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import uuid
import warnings
import os
from dotenv import load_dotenv

load_dotenv()

# Ignore all warnings
warnings.filterwarnings("ignore")

# Function to generate pre-signed URL
def generate_presigned_url(s3_uri):
    parsed_url = urlparse(s3_uri)
    bucket_name = parsed_url.netloc
    object_key = parsed_url.path.lstrip('/')
    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': object_key},
        ExpiresIn=3600
    )
    return presigned_url

# Function to retrieve documents, generate URLs, and format the response
def retrieve_and_format_response(query, retriever, llm):
    docs = retriever.get_relevant_documents(query)
    
    formatted_docs = []
    for doc in docs:
        content_data = doc.page_content
        s3_uri = doc.metadata['id']
        s3_gen_url = generate_presigned_url(s3_uri)
        formatted_doc = f"{content_data}\n\n[More Info]({s3_gen_url})"
        formatted_docs.append(formatted_doc)
    
    combined_content = "\n\n".join(formatted_docs)
    # print(combined_content)
    
    # Create a prompt for the LLM to generate an explanation based on the retrieved content
    prompt = f"Instruction: You are a helpful assistant to help users with their patient education queries. \
               Based on the following information, provide a summarized & concise explanation using a couple of sentences. \
               Only respond with the information relevant to the user query {query}, \
               if there are none, make sure you say the `magic words`: 'I don't know, I did not find the relevant data in the knowledge base.' \
               But you could carry out some conversations with the user to make them feel welcomed and comfortable, in that case you don't have to say the `magic words`. \
               In the event that there's relevant info, make sure to attach the download button at the very end: \n\n[More Info]({s3_gen_url}) \
               Context: {combined_content}"
    
    # Create the messages for the LLM input
    messages = [HumanMessage(content=prompt)]
    
    # Generate the response using the LLM
    response = llm(messages=messages)
    return {"answer": response.content}


# Function to save chat history to a file
def save_chat_history_to_file(filename, history):
    with open(filename, 'w') as file:
        file.write(history)

# Function to upload the file to S3
def upload_file_to_s3(bucket, key, filename):
    s3_client.upload_file(filename, bucket, key)


# Main loop to interact with the chatbot
if __name__ == "__main__":
    # Setup API keys
    os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
    os.environ["VOYAGE_AI_API_KEY"] = os.getenv("VOYAGE_AI_API_KEY")
    os.environ["PINECONE_API_KEY"] = os.getenv("PINECONE_API_KEY")
    
    # Setup AWS
    # Initiate a random session ID

    s3_client = boto3.client("s3")
    bucket_name = "chat-history-process"
    session_id = str(uuid.uuid4())
    chat_history_key = f"raw-data/chat_history_{session_id}.txt"

    # VOYAGE AI
    model_name = "voyage-large-2"  
    embeddings = VoyageAIEmbeddings(
        model=model_name,  
        voyage_api_key=os.environ["VOYAGE_AI_API_KEY"]
    )
    # PINECONE
    pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
    index_name = "test"

    # Retriever
    docsearch = PineconeVectorStore.from_existing_index(
        index_name=index_name,
        embedding=embeddings
    )
    
    # Initialize the OpenAI model
    llm = ChatOpenAI(model="gpt-4o", openai_api_key=openai.api_key)

    # Create a simple chat prompt template
    prompt_template = ChatPromptTemplate.from_template(
        "Instruction: You are a helpful assistant to help users with their patient education queries. \
        Based on the following information, provide a summarized & concise explanation using a couple of sentences. \
        Only respond with the information relevant to the user query {query}, \
        if there are none, make sure you say the `magic words`: 'I don't know, I did not find the relevant data in the knowledge base.' \
        But you could carry out some conversations with the user to make them feel welcomed and comfortable, in that case you don't have to say the `magic words`. \
        In the event that there's relevant info, make sure to attach the download button at the very end: \n\n[More Info]({s3_gen_url}) \
        Context: {combined_content}"
    )

    print("Simple Chatbot with Memory (Type 'exit' to quit)")
    chat_history = f"\nSession ID: {session_id}\n"
    while True:
        # INPUT #
        user_input = input("You: ")
        # INPUT #
        if user_input.lower() == "exit":
            break
        response = retrieve_and_format_response(user_input, docsearch.as_retriever(), llm)
        # OUTPUT #
        print(f"Bot: {response['answer']}")
        # OUTPUT #
        # Append interaction to chat history
        chat_history += f"You: {user_input}\nAI: {response}\n"
    # Save the chat history to a file
    local_filename = f"./history/chat_history_{session_id}.txt"
    save_chat_history_to_file(local_filename, chat_history)

    # Upload the file to S3
    upload_file_to_s3(bucket_name, chat_history_key, local_filename)
    print(f"Chat history saved and uploaded to S3 as '{chat_history_key}' in bucket '{bucket_name}'")