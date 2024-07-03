import openai
from langchain.chains import LLMChain
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.memory import ConversationBufferMemory
import boto3
import uuid
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# Setup
s3_client = boto3.client("s3",
                         aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                         aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"))
# Initiate a random session ID
bucket_name = "chat-history-process"
session_id = str(uuid.uuid4())
chat_history_key = f"raw-data/chat_history_{session_id}.txt"

# Initialize the OpenAI model
llm = ChatOpenAI(model="gpt-4o",openai_api_key=os.getenv("OPENAI_API_KEY"))

# Create a simple chat prompt template
prompt_template = ChatPromptTemplate.from_template(
    "You are a helpful assistant. Answer the user's question: {question}"
)

# Initialize the conversation memory
memory = ConversationBufferMemory()

# Initialize the LLMChain with the model, prompt template, and memory
chat_chain = LLMChain(llm=llm, prompt=prompt_template, memory=memory)

# Define a function to get a response from the chatbot
def get_chatbot_response(question):
    response = chat_chain.invoke(question)
    return response["text"]

# Define a function to save chat history to a file
def save_chat_history_to_file(filename, history):
    with open(filename, 'w') as file:
        file.write(history)

# Define a function to upload the file to S3
def upload_file_to_s3(bucket, key, filename):
    s3_client.upload_file(filename, bucket, key)

# Main loop to interact with the chatbot
if __name__ == "__main__":
    print("Simple Chatbot with Memory (Type 'exit' to quit)")
    chat_history = f"\nSession ID: {session_id}\n"
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        response = get_chatbot_response(user_input)
        print(f"Bot: {response}")
        # Append interaction to chat history
        chat_history += f"You: {user_input}\nAI: {response}\n"
    
    # Ensure the history directory exists
    os.makedirs("./history", exist_ok=True)


    # Save the chat history to a file
    local_filename = f"./history/chat_history_{session_id}.txt"
    save_chat_history_to_file(local_filename, chat_history)

    # Upload the file to S3
    upload_file_to_s3(bucket_name, chat_history_key, local_filename)

    print(f"Chat history saved and uploaded to S3 as '{chat_history_key}' in bucket '{bucket_name}'")