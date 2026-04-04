# DocChat_AWS_Bedrock_RAG
Chat with your own document using AWS Bedrock Knowledgebase, lambda and Claude. 

A fully serverless RAG (Retrieval-Augmented Generation) application that lets users upload PDF documents and have intelligent conversations with their content directly in a browser.

Built entirely on AWS managed services — no servers to manage.

##Live Demo
https://pdf-chat-ui-2026.s3.us-east-1.amazonaws.com/index.html

## Architecture

| Service | Role |
|---|---|
| Amazon Bedrock Knowledge Base | Chunks, embeds, and indexes PDFs automatically |
| Claude 3 Sonnet (Bedrock) | Generates grounded answers from retrieved context |
| Titan Embeddings (Bedrock) | Converts text to semantic vectors |
| AWS Lambda (x3) | Query orchestration, upload URLs, auto-sync |
| Amazon API Gateway | HTTPS endpoints for the browser |
| Amazon S3 | PDF storage + static website hosting |
| Amazon DynamoDB | Chat session memory |
| Amazon CloudFront | HTTPS CDN for the frontend |

## How it Works

**Ingestion Pipeline** (runs once per PDF):
User uploads PDF → S3 stores it → Lambda triggers → Bedrock Knowledge Base extracts text, chunks it, embeds with Titan, stores vectors in Aurora Serverless

**Query Pipeline** (runs per question):
User asks question → API Gateway → Lambda retrieves top-5 relevant chunks → injects into Claude prompt → answer returned with page citations

### Quick Start

1. Create two S3 buckets — one for PDFs, one for hosting
2. Enable Bedrock model access (Claude 3 Sonnet + Titan Embeddings)
3. Create a Bedrock Knowledge Base pointed at your PDF bucket
4. Deploy the three Lambda functions with the correct environment variables
5. Create API Gateway with /chat and /upload-url endpoints
6. Upload index.html to your hosting bucket
7. Open the CloudFront URL, click Settings, enter your API URL

## Tech Stack

- **AI/ML**: Amazon Bedrock (Claude 3 Sonnet, Titan Embeddings)
- **Compute**: AWS Lambda (Python 3.12)
- **API**: Amazon API Gateway
- **Storage**: Amazon S3, Amazon DynamoDB
- **Vector DB**: Aurora Serverless v2 (managed by Bedrock)
- **CDN**: Amazon CloudFront
- **Frontend**: Vanilla HTML, CSS, JavaScript (no framework)
