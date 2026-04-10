import json
import boto3
import os
from datetime import datetime
from botocore.config import Config

BUCKET = os.environ['S3_BUCKET']
REGION = os.environ.get('AWS_REGION', 'us-east-1')

s3 = boto3.client(
    's3',
    region_name=REGION,
    config=Config(signature_version='s3v4')
)

def lambda_handler(event, context):

    # Handle CORS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return respond(200, {})

    # Log the raw event so we can see exactly what arrived
    print('Event received:', json.dumps(event))

    # Parse body — handle both string and dict
    raw_body = event.get('body') or '{}'
    if isinstance(raw_body, str):
        body = json.loads(raw_body)
    else:
        body = raw_body

    print('Parsed body:', body)

    # Extract user ID from Cognito JWT token
    try:
        user_id = event['requestContext']['authorizer']['claims']['sub']
        print(f'Authenticated user: {user_id}')
    except KeyError as e:
        print(f'Authentication error: missing {e}')
        return respond(401, {'error': 'User not authenticated. Please log in.'})
    except Exception as e:
        print(f'Unexpected auth error: {str(e)}')
        return respond(401, {'error': 'Authentication failed.'})

    file_name = body.get('fileName', '').strip()
    print('fileName received:', repr(file_name))

    # Accept any file — we will just generate the URL
    # The browser already filters to PDF only
    if not file_name:
        return respond(400, {'error': 'fileName is required'})

    # Add .pdf extension if somehow missing
    if not file_name.lower().endswith('.pdf'):
        file_name = file_name + '.pdf'

    # Unique key with user isolation
    ts  = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    key = f'pdfs/{user_id}/{ts}_{file_name}'

    try:
        upload_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket':      BUCKET,
                'Key':         key,
                'ContentType': 'application/pdf',
            },
            ExpiresIn=300,
        )

        print('Generated URL for key:', key)

        return respond(200, {
            'uploadUrl': upload_url,
            's3Key':     key,
        })

    except Exception as e:
        print('Error:', str(e))
        return respond(500, {'error': str(e)})


def respond(code, body):
    return {
        'statusCode': code,
        'headers': {
            'Content-Type':                'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',  # Added Authorization
            'Access-Control-Allow-Methods': 'POST,OPTIONS',
        },
        'body': json.dumps(body),
    }