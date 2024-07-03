import os
import openai
from openai import OpenAI
import sounddevice as sd
from scipy.io.wavfile import write
from pydub import AudioSegment
from pydub.playback import play
from langchain.chains import LLMChain
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.memory import ConversationBufferMemory
from pydub import AudioSegment
from pydub.playback import play

# Initialize the OpenAI model
llm = ChatOpenAI(model="gpt-4o", openai_api_key=openai.api_key)

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

# Function to record audio
def record_audio(duration=5, fs=44100, filename="input.wav"):
    print("Recording...")
    recording = sd.rec(int(duration * fs), samplerate=fs, channels=1)
    sd.wait()
    write(filename, fs, recording)
    print("Recording complete.")
    return filename

# Function to transcribe audio
def transcribe_audio(audio_path):
    client = OpenAI()
    audio_file = open(audio_path, "rb")
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )
    return transcription.text

# Function to convert text to speech and play it
def text_to_speech(text, filename="./output.mp3"):
    client = OpenAI()
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text
    )
    response.stream_to_file(filename)
    # Play the MP3 file
    sound = AudioSegment.from_mp3(filename)
    play(sound)


# Main loop to interact with the chatbot
if __name__ == "__main__":
    print("Simple Chatbot with Memory and TTS/STT (Type 'exit' to quit)")
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        elif user_input.lower() == "speak":
            audio_path = record_audio()
            user_input = transcribe_audio(audio_path)
            print(f"You (transcribed): {user_input}")

        response = get_chatbot_response(user_input)
        print(f"Bot: {response}")
        text_to_speech(response)
