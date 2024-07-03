# Libraries natively supported by AWS Lambda
import json
import boto3
from io import BytesIO
import hashlib
import os
import tempfile
import csv
# Libraries below are from added layer(s)
# import openai
# import pypdf
import tiktoken
import urllib
from langchain_community.document_loaders import PyPDFLoader


print('Loading function')

# # OpenAI lib setup
# openai.api_key = os.getenv("OPENAI_API_KEY")

# Init s3 client
s3_client = boto3.client('s3')

def num_tokens_from_string(string: str, encoding_name="cl100k_base") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens

def split_into_chunks(text, count_tokens, max_tokens=8000):
    words = text.split()  # Splitting the text into words
    chunks = []
    current_chunk = []
    current_token_count = 0

    for word in words:
        # Include the current word in the token count
        word_token_count = count_tokens(word)
        new_token_count = current_token_count + word_token_count
        
        # Check if adding the current word would exceed the max_tokens limit
        if new_token_count > max_tokens:
            # If so, start a new chunk
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_token_count = word_token_count
        else:
            # Otherwise, add the word to the current chunk
            current_chunk.append(word)
            current_token_count = new_token_count

    # Don't forget to add the last chunk if it's not empty
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks

def short_hash(input_string, length=8):
    # Encode the input string to a bytes object
    input_bytes = input_string.encode('utf-8')
    # Create a SHA-256 hash object
    hash_object = hashlib.sha256(input_bytes)
    # Get the hexadecimal representation of the digest
    hex_digest = hash_object.hexdigest()
    # Truncate the hex digest to the desired length
    short_hash = hex_digest[:length]
    return short_hash

def load_and_parse_pdf(bucket_name, file_key, client=s3_client):
    # Get Object from S3
    response = client.get_object(Bucket=bucket_name, Key=file_key)
    file_stream = response['Body']
    
    # Convert the stream to bytes
    pdf_bytes = file_stream.read()

    # Write bytes to a temporary file
    with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf') as tmpfile:
        tmpfile.write(pdf_bytes)
        tmpfile.seek(0) # Go back to the beginning of the file after writing

        # Initialize PyPDFLoader with the path to the temporary file
        loader = PyPDFLoader(file_path=tmpfile.name)
        # Load and parse the document
        document = loader.load()

    # Return the loaded document
    return "".join([x.page_content for x in document])

def load_raw_text(bucket_name, file_key, client=s3_client):
    # Get the object from the bucket
    obj = client.get_object(Bucket=bucket_name, Key=file_key)
    # Read the file content
    document = obj['Body'].read().decode('utf-8')
    return document

def process_structured_data(bucket_name, file_key, client=s3_client):
    # Define source data paths
    copy_source = {
        'Bucket': bucket_name,
        'Key': file_key
    }
    
    # Get the object from S3
    response = s3.get_object(Bucket=copy_source["Bucket"], Key=copy_source["Key"])
    content_type = response['ContentType']
    file_content = response['Body'].read().decode('utf-8')
    
    # Use StringIO to treat the file content as a file-like object for csv.DictReader
    csvfile = StringIO(file_content)
    # Determine the file type (CSV or TSV) and set the appropriate delimiter
    delimiter = '\t' if file_key.endswith('.tsv') else ','
    
    # Read file
    reader = csv.DictReader(csvfile, delimiter=delimiter)
    # Split rows and further process them
    # Initiate a json
    for row in reader:
        total_token = num_tokens_from_string(row)
        chunk_data = {}
        # Hash the contents of the paragraph
        file_hash = short_hash(row)
        # Format the label with leading zeros
        label = f"staging/{copy_source['Key'].split('.')[0]}_row_data_{file_hash}.json"  # 5 digits with leading zeros, adjust as needed
        # Construct the JSON
        chunk_data["source"] = "s3://"+copy_source["Bucket"]+"/"+copy_source["Key"]
        chunk_data["content_hash"] = file_hash
        chunk_data["content"] = row
        chunk_data["token_count"] = total_token
        # Save to staging
        json_data_string = json.dumps(chunk_data)
        s3_client.put_object(Bucket=copy_source["Bucket"], Key=label, Body=json_data_string)
    print("Data chunked and saved to staging.")
    return None

def lambda_handler(event, context):
    # Get the object from the event and show its content type
    bucket = event['Records'][0]['s3']['bucket']['name']
    key_encoded = event['Records'][0]['s3']['object']['key']
    key = urllib.parse.unquote_plus(key_encoded)
    print(bucket)
    print(key_encoded)
    print(key)
    
    # Different processing for different file types 
    if key.lower().endswith(".pdf"):
        document = load_and_parse_pdf(bucket_name=bucket, file_key=key)
    elif key.lower().endswith(".txt"):
        document = load_raw_text(bucket_name=bucket, file_key=key)
    elif key.lower().endswith(".csv") or key.lower().endswith(".tsv"):
        process_structured_data(bucket_name=bucket, file_key=key)
    else:
        print(f"New file type detected from {key}, please adjust logic for processing file type: {key.split('.')[-1]}.")
    # Based on the document length, determine whether to chunk the file or not
    # Raw file nomenclature cannot have "." or " "
    # 1) Chunk document into paragraphs
    # Constraints: OpenAI embedding model text-embedding-3-small/text-embedding-3-large can only take 8191 tokens
    # 2) Count the tokens for each chunk
    # Each chunk should be less than 8000 tokens (~6000 words) to ensure that things are working
    # Chunking nomenclature: {file_key}_parag_{paragraph_id}_{hash_for_chunk_content}.{file_type}
    ## paragraph_id example: 00000
    ## hash_for_chunk_content: use hashlib to generate some short hash strings
    
    # Process the `document` var that now contains the raw strings
    if document:
        # Create paragraphs
        paragraphs = document.split('\n\n')
        # Filter out any empty paragraphs that might be created due to excessive newlines
        paragraphs = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
        
        # labelling the paragraphs
        label_number = 0
        for paragraph in paragraphs:
            total_token = num_tokens_from_string(paragraph)
            if total_token <= 8000:
                # Initiate a json
                chunk_data = {}
                # Hash the contents of the paragraph
                file_hash = short_hash(paragraph)
                # Format the label with leading zeros
                label = f"{key.split('.')[0].replace('raw', 'staging')}_parag_{'{:05d}'.format(label_number)}_{file_hash}.json"  # 5 digits with leading zeros, adjust as needed
                # Construct the JSON
                chunk_data["source"] = "s3://"+bucket+"/"+key
                chunk_data["content_hash"] = file_hash
                chunk_data["content"] = paragraph
                chunk_data["token_count"] = total_token
                # Save to staging
                json_data_string = json.dumps(chunk_data)
                s3_client.put_object(Bucket=bucket, Key=label, Body=json_data_string)
            else:
                # Chunking: Further breakdown the paragraph since it has more than 8000 tokens
                chunks = split_into_chunks(paragraph, num_tokens_from_string)
                for chunk in chunks:
                    # Initiate a json
                    chunk_data = {}
                    # Hash the chunk
                    file_hash = short_hash(chunk)
                    label = f"{key.split('.')[0].replace('raw', 'staging')}_parag_{'{:05d}'.format(label_number)}_{file_hash}.json"
                    # Save data using the label as the file_key
                    # Construct the JSON
                    chunk_data["source"] = "s3://"+bucket+"/"+key
                    chunk_data["paragraph_id"] = '{:05d}'.format(label_number)
                    chunk_data["content_hash"] = file_hash
                    chunk_data["content"] = chunk
                    chunk_data["token_count"] = num_tokens_from_string(chunk)
                    # Save to staging
                    json_data_string = json.dumps(chunk_data)
                    s3_client.put_object(Bucket=bucket, Key=label, Body=json_data_string)
            # Increment the label for the next iteration
            label_number += 1
            print("Unstructured data processed.")
        return "Unstructured data processed."
    else:
        print("Received structured data type, data copy completed.")
        return "Received structured data type, data copy completed."