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





## Phase 2 — Frontend, Authentication & Deployment

### What was added in this update

After the backend was working, the project was extended into a 
fully deployed public web application available at 
**[askyourpdf.org](https://askyourpdf.org)**

---

### New files and changes

| File | What changed |
|---|---|
| `index.html` | Complete browser UI — new file |
| `pdf-chat-query/lambda_function.py` | Fixed document scoping using correct S3 URI filter |
| `pdf-presign-url/lambda_function.py` | New Lambda for secure S3 uploads via pre-signed URLs |
| `pdf-kb-auto-sync/lambda_function.py` | New Lambda to auto-trigger Knowledge Base sync on upload |

---

### What was built

**Browser UI (index.html)**
A single HTML file — no frameworks, no build tools. Dark-themed 
chat interface with a document sidebar, upload zone, chat thread, 
source citations, and a settings modal. Hosted on S3 + CloudFront.

**User Authentication**
Amazon Cognito handles signup, email verification, and login. 
Every API call requires a valid JWT token. Only registered users 
can upload documents and ask questions.

**Secure PDF Upload**
The `pdf-presign-url` Lambda generates a temporary 5-minute 
signed S3 URL. The browser uploads the PDF directly to S3 — 
no AWS credentials ever touch the frontend code.

**Automatic Knowledge Base Sync**
The `pdf-kb-auto-sync` Lambda is triggered by S3 every time a 
PDF is uploaded. It calls the Bedrock StartIngestionJob API so 
documents are searchable within ~45 seconds of upload — no 
manual sync needed.

**Document Scoping Fix**
Answers now come only from the document the user selected. 
The query Lambda filters using the built-in 
`x-amz-bedrock-kb-source-uri` metadata field — the exact S3 
URI of the selected document.

---

### AWS services added in Phase 2

| Service | Purpose |
|---|---|
| Amazon Cognito | User registration and JWT authentication |
| CloudFront | HTTPS and global CDN for the frontend |
| Route 53 | Custom domain — askyourpdf.org |
| AWS Certificate Manager | Free SSL certificate for HTTPS |
| S3 (second bucket) | Hosts the index.html static website (it was there in the first commit too) |

---

### How to use the app

1. Visit **https://askyourpdf.org**
2. Create an account with your email — verify with the 6-digit code
3. Sign in
4. Drag and drop a PDF onto the sidebar
5. Wait ~45 seconds for the green dot to appear
6. Click the document and start asking questions
7. Every answer includes the source filename and page number

---

### Full technical report

See `phase2_report_final.docx` in the repository releases for 
the complete step-by-step breakdown of everything built, 
why each decision was made, and every problem encountered 
during deployment with its fix.
