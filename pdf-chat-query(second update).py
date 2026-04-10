import json
import os
import boto3
import uuid
from datetime import datetime
from typing import List, Dict, Any
S3_BUCKET = os.environ.get('S3_BUCKET', '')

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
def get_history(session_id: str) -> List[Dict]:
    """Fetch recent messages from DynamoDB, sorted chronologically."""
    try:
        resp = history_tbl.query(
            KeyConditionExpression=Key('session_id').eq(session_id),
            ScanIndexForward=False,  # Get newest first to respect Limit
            Limit=MAX_HISTORY
        )
        items = resp.get('Items', [])
        # Sort them back to chronological order (User then Assistant) for the LLM
        return sorted(items, key=lambda x: x['timestamp'])
    except Exception as e:
        print(f"Error fetching history: {e}")
        return []

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

# ── KNOWLEDGE BASE RETRIEVAL WITH FILTERING ─────────────────────────────────
def retrieve_chunks(question: str, s3_key: str = None) -> list:
    """
    Retrieve relevant chunks from the knowledge base.
    Filters by the exact S3 URI of the selected document.
    Uses the built-in x-amz-bedrock-kb-source-uri metadata field
    which Bedrock automatically populates for every indexed chunk.
    """

    retrieval_config = {
        'vectorSearchConfiguration': {
            'numberOfResults': TOP_K,
        }
    }

    # Filter to the specific document using the S3 URI
    # This is the ONLY metadata field Bedrock Knowledge Base guarantees
    if s3_key and S3_BUCKET:
        full_uri = f's3://{S3_BUCKET}/{s3_key}'
        print(f'Filtering to document: {full_uri}')
        retrieval_config['vectorSearchConfiguration']['filter'] = {
            'equals': {
                'key':   'x-amz-bedrock-kb-source-uri',
                'value': full_uri
            }
        }

    try:
        response = bedrock_agent.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': question},
            retrievalConfiguration=retrieval_config
        )
    except Exception as e:
        print(f'Retrieve error: {e}')
        # If filter fails, retry without filter
        if s3_key:
            print('Retrying without filter...')
            return retrieve_chunks(question, s3_key=None)
        return []

    chunks = []
    for result in response.get('retrievalResults', []):
        location = result.get('location', {})
        s3_loc   = location.get('s3Location', {})
        metadata = result.get('metadata', {})
        chunks.append({
            'text':      result['content']['text'],
            'score':     result.get('score', 0),
            'source':    s3_loc.get('uri', 'unknown'),
            'page':      metadata.get('x-amz-bedrock-kb-chunk-page-number', 'N/A'),
            'file_name': s3_loc.get('uri', 'unknown').split('/')[-1],
        })

    print(f'Retrieved {len(chunks)} chunks')

    # If filtered search returned nothing, fall back to full KB search
    if not chunks and s3_key:
        print('No results with filter, trying without...')
        return retrieve_chunks(question)

    return chunks

# ── BUILD THE PROMPT ────────────────────────────────────────────────────────
def build_messages(question: str, chunks: List[Dict], history: List[Dict]) -> tuple:
    context_blocks = []
    for i, chunk in enumerate(chunks, 1):
        file_name = chunk.get('file_name', chunk['source'].split('/')[-1])
        page_info = f'Page {chunk["page"]}' if chunk['page'] != 'N/A' else ''
        header    = f'[Source {i}: {file_name} {page_info}]'.strip()
        context_blocks.append(f'{header}\n{chunk["text"]}')

    context_text = '\n\n---\n\n'.join(context_blocks)

    system_prompt = f"""You are a helpful assistant that answers questions about user-uploaded PDF documents.

STRICT RULES:
- Answer ONLY using the context provided below. Do not use your training knowledge.
- If the answer is not in the context, say: "I could not find this information in your uploaded documents."
- Always cite your source: mention the filename and page number.
- Be concise and direct.
- Remember that you can only access documents uploaded by this specific user.

CONTEXT FROM USER'S DOCUMENTS:
{context_text}"""

    messages = []
    for msg in history:
        messages.append({'role': msg['role'], 'content': msg['content']})

    messages.append({'role': 'user', 'content': question})
    return system_prompt, messages

# ── CALL CLAUDE ─────────────────────────────────────────────────────────────
def invoke_claude(system_prompt: str, messages: List[Dict]) -> str:
    try:
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
    except Exception as e:
        print(f"Error invoking Claude: {e}")
        return "I encountered an error generating a response. Please try again."

# ── LAMBDA HANDLER WITH USER ISOLATION ──────────────────────────────────────
def lambda_handler(event, context):
    try:
        # Extract user ID from the Cognito JWT token
        # API Gateway injects this automatically when Cognito authorizer is active
        user_id = event['requestContext']['authorizer']['claims']['sub']
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON in request body'})
    except KeyError as e:
        return _response(401, {'error': 'User not authenticated. Please log in.'})
    except Exception as e:
        return _response(500, {'error': f'Authentication error: {str(e)}'})

    question   = body.get('question', '').strip()
    s3_key     = body.get('s3Key', '').strip()  # Optional: filter to specific document
    session_id = body.get('session_id') or str(uuid.uuid4())

    if not question:
        return _response(400, {'error': '"question" field is required'})

    # Scope the session to this user (prevents cross-user session access)
    scoped_session_id = f"{user_id}_{session_id}"
    
    # 1. Get History from DynamoDB (scoped to user-specific session)
    history = get_history(scoped_session_id)

    # 2. Retrieve relevant chunks (only from user's documents)
    chunks = retrieve_chunks(question, s3_key=s3_key if s3_key else None)

    if not chunks:
        return _response(200, {
            'answer':     'No relevant content found in your uploaded documents. Please upload documents or try a different question.',
            'session_id': session_id,  # Return original session_id (without user prefix)
            'sources':    []
        })

    # 3. Build augmented prompt
    system_prompt, messages = build_messages(question, chunks, history)

    # 4. Generate answer
    answer = invoke_claude(system_prompt, messages)

    # 5. Persist the interaction to DynamoDB (with scoped session)
    save_messages(scoped_session_id, question, answer)

    # 6. Format citations for response
    sources = [
        {
            'file':  chunk.get('file_name', chunk['source'].split('/')[-1]),
            'page':  chunk['page'],
            'score': round(float(chunk['score']), 3),
        }
        for chunk in chunks
    ]

    return _response(200, {
        'answer':     answer,
        'session_id': session_id,  # Return original session_id (without user prefix)
        'sources':    sources,
    })

def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type':                'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true',
        },
        'body': json.dumps(body),
    }