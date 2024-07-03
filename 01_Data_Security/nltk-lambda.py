# File: lambda_function.py
import json
import nltk  # Natural Language Toolkit
from nltk import word_tokenize, pos_tag, ne_chunk  # Import specific NLTK functions
from nltk.tree import Tree  # Import the Tree data structure
import boto3

# Initialize S3 client
s3_client = boto3.client('s3')

# Set the NLTK data path to the included folder
nltk.data.path.append("/opt/python/lib/python3.11/site-packages/nltk_data")

def remove_names_and_locations(text):
    """
    Remove names of persons and locations from the given text using Named Entity Recognition (NER).

    :param text: The input text to process
    :return: Text with names and locations replaced by an empty string
    """
    # Tokenize the text into individual words
    tokenized_text = word_tokenize(text)

    # Perform Part-of-Speech (POS) tagging on the tokenized text
    tagged_text = pos_tag(tokenized_text)

    # Perform Named Entity Recognition (NER) to identify named entities in the tagged text
    chunked_text = ne_chunk(tagged_text)

    def extract_entity_names_and_locations(t):
        """
        Recursively extract entity names labeled as 'PERSON' or 'GPE' from the NER tree structure.

        :param t: NER tree node
        :return: List of names and locations recognized as 'PERSON' or 'GPE'
        """
        entity_names_and_locations = []

        # Check if the node has a label (is a subtree)
        if hasattr(t, 'label') and t.label:
            # If the label is 'PERSON' or 'GPE', it's a named entity representing a person's name or location
            if t.label() in ['PERSON', 'GPE']:
                # Join all child tokens (words) to form the complete entity name
                entity_names_and_locations.append(' '.join([child[0] for child in t]))
            else:
                # Recursively check each child node in the tree
                for child in t:
                    entity_names_and_locations.extend(extract_entity_names_and_locations(child))
        return entity_names_and_locations

    # Extract all names and locations recognized as 'PERSON' or 'GPE' from the chunked NER tree
    entity_names_and_locations = []
    for tree in chunked_text:
        entity_names_and_locations.extend(extract_entity_names_and_locations(tree))

    # Remove each recognized name and location from the original text by replacing it with an empty string
    cleaned_text = text
    for entity in entity_names_and_locations:
        cleaned_text = cleaned_text.replace(entity, '')

    return cleaned_text

# def lambda_handler(event, context):
#     # Example usage
#     text = "Hi I am Jason and I live in Toronto, I’m not feeling that well today because I have a runny nose and a headache."
#     cleaned_text = remove_names_and_locations(text)
#     return {
#         "statusCode": 200,
#         "body": json.dumps({"cleaned_text": cleaned_text})
#     }

def lambda_handler(event, context):
    # Define the bucket and target directories
    bucket = 'chat-history-process'
    source_prefix = 'raw-data/'
    target_prefix = 'desensitized-data/'
    
    # Extract the source key from the S3 event
    try:
        source_key = event['Records'][0]['s3']['object']['key']
        if not source_key.startswith(source_prefix) or not source_key.endswith('.txt'):
            return {
                'statusCode': 400,
                'body': 'Event does not match expected format'
            }
    except KeyError:
        return {
            'statusCode': 400,
            'body': 'Invalid S3 event format'
        }
    
    try:
        # Download the file from the source directory
        response = s3_client.get_object(Bucket=bucket, Key=source_key)
        file_content = response['Body'].read()

        # Perform processing on the file content (example: make all text uppercase)
        processed_content = file_content.decode('utf-8')
        cleaned_text = remove_names_and_locations(processed_content)

        
        # Define the target key (destination path)
        file_name = source_key.split('/')[-1]
        target_key = f'{target_prefix}{file_name}'
        
        # Upload the processed file to the destination directory
        s3_client.put_object(Bucket=bucket, Key=target_key, Body=cleaned_text.encode('utf-8'))
        
        # Delete the original file from the source directory
        s3_client.delete_object(Bucket=bucket, Key=source_key)
        
        return {
            'statusCode': 200,
            'body': f"File successfully moved from {source_key} to {target_key}"
        }
    except Exception as e:
        print(e)
        return {
            'statusCode': 500,
            'body': f"Error: {str(e)}"
        }