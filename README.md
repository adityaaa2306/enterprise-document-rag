Agentic Document Processing System

A production-ready intelligent document processing system with carbon-aware computing, speculative RAG, and full authentication. Built with FastAPI, Next.js, and AI-powered agents for sustainable, efficient document summarization.

## Features

- **Intelligent Document Processing**: Multi-agent system for document summarization
- **Carbon-Aware Computing**: Optimizes model selection based on grid carbon intensity
- **Speculative RAG**: Efficient retrieval-augmented generation with draft-verify architecture
- **Real-time Dashboard**: Monitor processing metrics, carbon savings, and efficiency
- **Modern UI**: Glassmorphism design with dark mode support

> **Chroma:** The application currently uses an embedded Chroma instance for
> cost-efficient portfolio deployment. The production deployment architecture
> supports migrating to a standalone Chroma server (`HttpClient`) with no
> application-level changes beyond restoring the client factory branch.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [Running on Cloud](#running-on-cloud)
- [API Documentation](#api-documentation)
- [Known Issues](#known-issues)
- [Dependencies](#dependencies)

---

## Project Overview

This system processes documents (PDFs, text files) through an intelligent multi-agent pipeline that:

1. **Triages** documents to extract and chunk content
2. **Summarizes** chunks using a tiered model approach (Light → Medium → Large)
3. **Routes** processing based on carbon intensity for sustainability
4. **Verifies** accuracy using fact-checking models
5. **Stores** embeddings for RAG-based question answering
6. **Tracks** carbon savings and processing metrics

### Key Components

- **Backend**: FastAPI server with SQLite database and ChromaDB vector store
- **Frontend**: Next.js 16 with TypeScript, Tailwind CSS v4, and Radix UI
- **AI Models** (NVIDIA NIM):
  - Light: Llama 3.2 3B (fallback: Gemma 2 2B)
  - Medium: Gemma 4 31B (fallback: Ministral 14B)
  - Heavy: Llama 3.3 70B (fallbacks: GPT OSS 120B → Qwen3.5 122B)
  - Embeddings: llama-nemotron-embed-1b-v2
  - Rerank: llama-nemotron-rerank-1b-v2
  - Accuracy gate: local RoBERTa NLI

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Login   │  │  Signup  │  │Dashboard │  │ New Job  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓ HTTP/REST API
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Authentication Layer                     │   │
│  │  • JWT Token Management  • Password Hashing          │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           Agentic Orchestrator (LangGraph)           │   │
│  │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  │   │
│  │  │Triage│→ │ Map  │→ │Carbon│→ │Reduce│→ │Store │  │   │
│  │  │Agent │  │Agent │  │Router│  │Agent │  │Agent │  │   │
│  │  └──────┘  └──────┘  └──────┘  └──────┘  └──────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  Storage Layer                        │   │
│  │  • SQLite (Users, Documents, Chunks)                 │   │
│  │  • ChromaDB (Vector Embeddings)                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                      AI Models (NVIDIA NIM)                  │
│  Light / Medium / Heavy LLMs + Nemotron embed & rerank      │
└─────────────────────────────────────────────────────────────┘
```

### Agent Workflow

1. **Triage Agent**: Extracts text from uploaded documents
2. **Map Agent**: Chunks text and generates initial summaries
3. **Carbon Router**: Selects optimal model based on grid intensity
4. **Reduce Agent**: Compiles final summary from chunk summaries
5. **Storage Agent**: Saves to database and generates embeddings

### Frontend Directory Structure

---

## Prerequisites

### Required Software

- **Python**: 3.10 or higher
- **Node.js**: 18.x or higher
- **npm/pnpm**: Latest version
- **Next.js**: 14.x or higher

### API Keys

- **NVIDIA API Key**: For NIM LLMs, embeddings, and reranking (required) — https://build.nvidia.com/settings/api-keys
- **Electricity Maps API Key**: For carbon intensity data (optional)

---

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd updated_multiagent
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
# or
pnpm install
```

### 4. NVIDIA NIM API Key

Get a free API key from [build.nvidia.com](https://build.nvidia.com/settings/api-keys) and set it in `backend/.env` as `NVIDIA_API_KEY`.

---

## Environment Variables

### Backend (.env)

Create a `.env` file in the `backend/` directory (copy from `.env.example`):

```bash
# NVIDIA NIM
NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
ELECTRICITY_MAPS_API_KEY=your_electricity_maps_key_here  # Optional

# Light / Medium / Heavy (primary + fallbacks)
LIGHT_MODEL_PRIMARY=meta/llama-3.2-3b-instruct
LIGHT_MODEL_FALLBACK=google/gemma-2-2b-it
MEDIUM_MODEL_PRIMARY=google/gemma-4-31b-it
MEDIUM_MODEL_FALLBACK=mistralai/ministral-14b-instruct-2512
HEAVY_MODEL_PRIMARY=meta/llama-3.3-70b-instruct
HEAVY_MODEL_FALLBACK_1=openai/gpt-oss-120b
HEAVY_MODEL_FALLBACK_2=qwen/qwen3.5-122b-a10b

# Retrieval
EMBEDDING_MODEL=nvidia/llama-nemotron-embed-1b-v2
RERANK_MODEL=nvidia/llama-nemotron-rerank-1b-v2
RAG_CANDIDATE_K=20
RAG_TOP_K=5

# Database
DATABASE_URL=sqlite:///./agentic_db.sqlite
VECTOR_DB_PATH=./local_db/chroma

# Carbon Settings
BASELINE_GRID_INTENSITY=450.0
LOCAL_GRID_INTENSITY=700.0

# Document Processing
TRIAGE_STRATEGY=fast

# Authentication (CHANGE IN PRODUCTION!)
JWT_SECRET_KEY=your-secret-key-change-this-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

## Frontend

frontend/
├── app/                  # Next.js App Router
├── login/               # Authentication pages
├── signup/
├── dashboard/           # Main dashboard
├── new-job/             # Document upload
├── results/             # Processing results
├── components/
├── ui/                  # Radix UI components
├── document-history/    # History viewer
├── upload-zone/         # File upload
├── strategy-selector/   # Mode selection
└── lib/                 # Utilities


## Backend Architecture

backend/
├── src/
│   ├── api/                 # FastAPI routes
│   │   ├── main.py          # Server & endpoints
│   │   ├── auth.py          # JWT utilities
│   │   └── schemas.py       # Pydantic models
│   ├── core/                # Business logic
│   │   ├── orchestrator.py  # LangGraph
│   │   └── config.py        # Settings
│   ├── agents/              # AI agents
│   │   └── models.py        # Model management
│   ├── carbon_router/       # Carbon logic
│   ├── memory/              # Data persistence
│   │   └── storage.py       # DB operations
│   └── monitoring/          # Metrics
└── local_db/                # Database


No additional environment variables required. API endpoint is configured to `http://localhost:8000`.

---

## Running Locally

### Start Backend Server

```bash
cd backend
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Backend will be available at: `http://localhost:8000`

### Start Frontend Development Server

```bash
cd frontend
npm run dev
# or
pnpm dev
```

Frontend will be available at: `http://localhost:3000`

### Access the Application

1. **Homepage**: `http://localhost:3000`
2. **Dashboard**: `http://localhost:3000/dashboard`
3. **New Job**: `http://localhost:3000/new-job`

---

## Running on Cloud

### Backend Deployment (Railway, Render, Fly.io)

1. **Update `requirements.txt`** if needed
2. **Set environment variables** in your cloud platform
3. **Change JWT_SECRET_KEY** to a strong random value
4. **Update DATABASE_URL** to use PostgreSQL (recommended for production):
   ```
   DATABASE_URL=postgresql://user:password@host:port/database
   ```
5. **Deploy** using platform-specific commands

### Frontend Deployment (Vercel, Netlify)

1. **Update API endpoint** in frontend code to point to your backend URL
2. **Deploy** via Git integration or CLI
3. **Configure environment variables** if needed

### Production Checklist

- [ ] Change `JWT_SECRET_KEY` to a strong random value
- [ ] Use PostgreSQL instead of SQLite
- [ ] Enable HTTPS/SSL
- [ ] Set up rate limiting
- [ ] Configure CORS for your domain
- [ ] Set up monitoring and logging
- [ ] Enable database backups

---

## API Documentation

### Authentication Endpoints

#### Register User
```http
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123",
  "full_name": "John Doe"
}
```

#### Login
```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123"
}

Response:
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer"
}
```

#### Get Current User
```http
GET /auth/me
Authorization: Bearer <token>
```

### Document Processing Endpoints

#### Submit Document
```http
POST /summarize
Content-Type: multipart/form-data

file: <document.pdf>
mode: "balanced" | "eco" | "performance"
```

#### Check Job Status
```http
GET /job-status/{job_id}
```

#### Get Job Result
```http
GET /job-result/{job_id}
```

#### RAG Query
```http
POST /rag-query
Content-Type: application/json

{
  "document_id": "uuid",
  "query": "What is the main topic?"
}
```

### Dashboard Endpoints

#### List Documents
```http
GET /documents
```

#### Get Dashboard Stats
```http
GET /dashboard-stats
```

Full API documentation available at: `http://localhost:8000/docs`

---

## Known Issues and Limitations

### Current Limitations

1. **File Size**: Large PDFs (>50MB) may timeout
2. **Concurrent Processing**: Limited to sequential job processing
3. **NVIDIA API Key**: Required for all LLM / embed / rerank calls
4. **SQLite**: Not recommended for production (use PostgreSQL)
5. **Token Invalidation**: No server-side token blacklist (logout is client-side only)

### Known Issues

1. **Bcrypt Warning**: Harmless warning about bcrypt version detection on Windows
2. **CORS**: May need adjustment for production domains
3. **Session Persistence**: JWT tokens stored in localStorage (consider httpOnly cookies for production)

### Workarounds

- **Large Files**: Split into smaller chunks before upload
- **NIM Rate Limits**: Within-tier fallbacks automatically try the next model
- **Token Expiry**: Re-login after 24 hours

---

## Dependencies

### Backend Dependencies

See [`backend/requirements.txt`](backend/requirements.txt):

- **FastAPI**: Web framework
- **uvicorn**: ASGI server
- **SQLAlchemy**: ORM for database
- **ChromaDB**: Vector database
- **LangGraph**: Agent orchestration
- **transformers**: Hugging Face models
- **torch**: PyTorch for ML
- **sentence-transformers**: Embeddings
- **ollama**: Local LLM interface
- **groq**: Cloud LLM API
- **passlib[bcrypt]**: Password hashing
- **python-jose[cryptography]**: JWT tokens
- **unstructured**: Document parsing

### Frontend Dependencies

See [`frontend/package.json`](frontend/package.json):

- **Next.js 16**: React framework
- **React 18**: UI library
- **TypeScript**: Type safety
- **Tailwind CSS v4**: Styling
- **Radix UI**: Component primitives
- **Recharts**: Data visualization
- **Lucide React**: Icons
- **Framer Motion**: Animations

---

---


