import voyageai
import pinecone
from pinecone import Pinecone, ServerlessSpec
import json
import os
import boto3
import urllib


# Init S3 client
s3 = boto3.client("s3")
# Init Voyage client - embedding model to create the vector
voyageai.api_key = os.getenv("VOYAGE_AI_API_KEY")
vo = voyageai.Client()
# Init Pinecone client - to store the vector and the contents
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
## HARD CODED index names and host
index_name = "test"
index = pc.Index(index_name, host="https://test-otned97.svc.aped-4627-b74a.pinecone.io")

## TASK DEFINITIONS:
## 1) Event would be new JSON files being created in the s3://data-brave-genai/staging/ lcoation
## 2) Read the json file, parse the "content" key
## 3) Create embedding vector using Voyage AI API
## 4) Ingest it into Pinecone index

def read_json_from_s3(event, s3_client=s3):
    # JSON Files
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    file_key = event['Records'][0]['s3']['object']['key']
    try:
        # Retrieve the JSON file from S3
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        # Read the file's content
        text = response["Body"].read().decode()
        json_data = json.loads(text)
        return json_data
    except Exception as e:
        print(e)
        return None

def lambda_handler(event, context):
    # Prepare ID
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    key_encoded = event['Records'][0]['s3']['object']['key']
    file_key = urllib.parse.unquote_plus(key_encoded)
    print(file_key)
    # Read and parse file
    content_data = read_json_from_s3(event, s3)
    # Create embedding
    id = f"s3://{bucket_name}/{file_key}"
    result = vo.embed(content_data["content"], model="voyage-large-2", input_type="document")
    vector = result.embeddings
    # Ingest into 
    index.upsert(vectors=[{"id": id, "values": vector[0], "metadata": {"id": id, "text": content_data["content"]}}])
    return {
        'statusCode': 200,
        'body': json.dumps("Data ingested into Pinecone index."),
        'file': file_key
    }