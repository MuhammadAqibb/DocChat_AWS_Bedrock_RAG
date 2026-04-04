import json
import os
import boto3
import uuid
from datetime import datetime
from decimal import Decimal
from boto3.dynamodb.conditions import Key  # Required for DynamoDB queries

# ── CONFIGURATION ──────────────────────────────────────────────────────────
KNOWLEDGE_BASE_ID = os.environ['KNOWLEDGE_BASE_ID']
REGION            = os.environ.get('BEDROCK_REGION', 'us-east-1')
CLAUDE_MODEL_ID   = os.environ.get('CLAUDE_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')

TOP_K = 5
MAX_HISTORY = 6

# ── AWS CLIENTS ─────────────────────────────────────────────────────────────
bedrock_agent = boto3.client('bedrock-agent-runtime', region_name=REGION)
bedrock_rt    = boto3.client('bedrock-runtime',       region_name=REGION)
dynamodb      = boto3.resource('dynamodb', region_name=REGION)
history_tbl   = dynamodb.Table('ChatHistory')

# ── DYNAMODB PERSISTENCE ────────────────────────────────────────────────────
def get_history(session_id: str) -> list[dict]:
    """Fetch recent messages from DynamoDB, sorted chronologically."""
    resp = history_tbl.query(
        KeyConditionExpression=Key('session_id').eq(session_id),
        ScanIndexForward=False,  # Get newest first to respect Limit
        Limit=MAX_HISTORY
    )
    items = resp.get('Items', [])
    # Sort them back to chronological order (User then Assistant) for the LLM
    return sorted(items, key=lambda x: x['timestamp'])

def save_messages(session_id: str, question: str, answer: str):
    """Persist both turns of the conversation to DynamoDB."""
    ts_base = datetime.utcnow().isoformat()
    
    # Store User Message
    history_tbl.put_item(Item={
        'session_id': session_id,
        'timestamp':  f"{ts_base}-user",
        'role':       'user',
        'content':    question,
    })
    
    # Store Assistant Message
    history_tbl.put_item(Item={
        'session_id': session_id,
        'timestamp':  f"{ts_base}-assistant",
        'role':       'assistant',
        'content':    answer,
    })

# ── KNOWLEDGE BASE RETRIEVAL ────────────────────────────────────────────────
def retrieve_chunks(question: str) -> list[dict]:
    response = bedrock_agent.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={'text': question},
        retrievalConfiguration={
            'vectorSearchConfiguration': {
                'numberOfResults': TOP_K
            }
        }
    )

    chunks = []
    for result in response.get('retrievalResults', []):
        location = result.get('location', {})
        s3_loc   = location.get('s3Location', {})
        metadata = result.get('metadata', {})

        chunks.append({
            'text':   result['content']['text'],
            'score':  result.get('score', 0),
            'source': s3_loc.get('uri', 'unknown'),
            'page':   metadata.get('x-amz-bedrock-kb-chunk-page-number', 'N/A'),
        })
    return chunks

# ── BUILD THE PROMPT ────────────────────────────────────────────────────────
def build_messages(question: str, chunks: list[dict], history: list[dict]) -> tuple:
    context_blocks = []
    for i, chunk in enumerate(chunks, 1):
        file_name = chunk['source'].split('/')[-1]
        page_info = f'Page {chunk["page"]}' if chunk['page'] != 'N/A' else ''
        header    = f'[Source {i}: {file_name} {page_info}]'.strip()
        context_blocks.append(f'{header}\n{chunk["text"]}')

    context_text = '\n\n---\n\n'.join(context_blocks)

    system_prompt = f"""You are a helpful assistant that answers questions about PDF documents.

STRICT RULES:
- Answer ONLY using the context provided below. Do not use your training knowledge.
- If the answer is not in the context, say: "I could not find this in the uploaded documents."
- Always cite your source: mention the filename and page number.
- Be concise and direct.

CONTEXT FROM DOCUMENTS:
{context_text}"""

    messages = []
    for msg in history:
        messages.append({'role': msg['role'], 'content': msg['content']})

    messages.append({'role': 'user', 'content': question})
    return system_prompt, messages

# ── CALL CLAUDE ─────────────────────────────────────────────────────────────
def invoke_claude(system_prompt: str, messages: list[dict]) -> str:
    body = {
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': 1024,
        'system':   system_prompt,
        'messages': messages,
    }
    response = bedrock_rt.invoke_model(
        modelId=CLAUDE_MODEL_ID,
        contentType='application/json',
        accept='application/json',
        body=json.dumps(body),
    )
    result = json.loads(response['body'].read())
    return result['content'][0]['text']

# ── LAMBDA HANDLER ──────────────────────────────────────────────────────────
def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})

    question   = body.get('question', '').strip()
    session_id = body.get('session_id') or str(uuid.uuid4())

    if not question:
        return _response(400, {'error': '"question" field is required'})

    # 1. Get History from DynamoDB
    history = get_history(session_id)

    # 2. Retrieve relevant chunks
    chunks = retrieve_chunks(question)

    if not chunks:
        return _response(200, {
            'answer':     'No relevant content found in the uploaded documents.',
            'session_id': session_id,
            'sources':    []
        })

    # 3. Build augmented prompt
    system_prompt, messages = build_messages(question, chunks, history)

    # 4. Generate answer
    answer = invoke_claude(system_prompt, messages)

    # 5. Persist the interaction to DynamoDB
    save_messages(session_id, question, answer)

    # 6. Format citations for response
    sources = [
        {
            'file':  chunk['source'].split('/')[-1],
            'page':  chunk['page'],
            'score': round(float(chunk['score']), 3),
        }
        for chunk in chunks
    ]

    return _response(200, {
        'answer':     answer,
        'session_id': session_id,
        'sources':    sources,
    })

def _response(status_code: int, body: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type':                'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body),
    }