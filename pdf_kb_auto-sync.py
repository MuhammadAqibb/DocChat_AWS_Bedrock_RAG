# pdf-kb-auto-sync/lambda_function.py
# Triggered by S3 ObjectCreated events.
# Starts a Bedrock Knowledge Base ingestion job whenever a PDF is uploaded.
import os, json, boto3

KNOWLEDGE_BASE_ID = os.environ['KNOWLEDGE_BASE_ID']
DATA_SOURCE_ID    = os.environ['DATA_SOURCE_ID']  # from KB console
REGION            = os.environ.get('BEDROCK_REGION', 'us-east-1')

bedrock_agent = boto3.client('bedrock-agent', region_name=REGION)

def lambda_handler(event, context):
    for record in event['Records']:
        key = record['s3']['object']['key']
        print(f'New file uploaded: {key} — starting KB sync')

    # Start ingestion job — Bedrock will process all new/changed files
    response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID,
    )
    job_id = response['ingestionJob']['ingestionJobId']
    print(f'Ingestion job started: {job_id}')
    return {'statusCode': 200, 'body': json.dumps({'jobId': job_id})}
