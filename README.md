# AI Streaming API

A reliable AI streaming API built with **FastAPI**, **RabbitMQ**, **Redis Streams**, **MySQL**, and **Azure OpenAI**. Submit prompts to be processed asynchronously and stream responses token-by-token via Server-Sent Events (SSE).

## 📖 Detailed Write-up

I’ve written a detailed blog explaining the architecture, design decisions, and implementation of this project:

🔗 Read here: [Medium Blog – Project Explanation](https://medium.com/@turenchotara7/list/reading-list)

## Architecture

```
Client (Browser)
  │
  ├── POST /api/prompt ──► FastAPI ──► MySQL (save) ──► RabbitMQ (queue)
  │
  └── GET /api/stream/{id} ◄── SSE ◄── Redis Stream ◄── Worker
                                                          │
                                                     Azure OpenAI
```

| Component        | Role                                                                 |
|------------------|----------------------------------------------------------------------|
| **FastAPI**      | HTTP API + SSE streaming endpoint + serves the web UI                |
| **RabbitMQ**     | Message broker — decouples prompt submission from AI processing      |
| **Redis Streams**| Temporary token storage — enables real-time streaming and replay      |
| **MySQL**        | Persistent storage — prompt history, status, and full responses      |
| **Azure OpenAI** | AI model for generating streaming chat completions                   |
| **Worker**       | Background consumer — reads from RabbitMQ, calls AI, writes to Redis |

## Project Structure

```
stream-app/
├── app/
│   ├── __init__.py
│   ├── config.py          # Settings via pydantic-settings (.env)
│   ├── database.py        # Async SQLAlchemy engine + session
│   ├── main.py            # FastAPI app, lifespan, CORS, routes
│   ├── models.py          # SQLAlchemy Prompt model
│   ├── rabbitmq.py        # RabbitMQ connect / publish / consume
│   ├── redis_stream.py    # Redis Streams XADD / XREAD helpers
│   ├── schemas.py         # Pydantic request/response schemas
│   ├── worker.py          # Standalone worker process
│   ├── routes/
│   │   ├── __init__.py
│   │   └── prompt.py      # /api/prompt, /api/stream/{id}, /api/prompt/{id}
│   └── templates/
│       └── index.html      # Web UI (single-page app)
├── requirements.txt
├── .env.example
└── README.md
```

## Prerequisites

- **Python 3.10+**
- **MySQL** (running and accessible)
- **RabbitMQ** (running and accessible)
- **Redis** (running and accessible)
- **Azure OpenAI** resource with a deployed chat model

## Setup

### 1. Clone and create a virtual environment

```bash
cd stream-app
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=stream_app

# RabbitMQ
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Azure OpenAI
AZURE_OPENAI_API_KEY=your-azure-openai-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=your-deployment-name

# App
APP_HOST=0.0.0.0
APP_PORT=8000
```

### 4. Create the MySQL database

```sql
CREATE DATABASE stream_app;
```

The `prompts` table is auto-created on startup via SQLAlchemy.

## Running

You need **two separate terminals** — one for the FastAPI server and one for the worker.

### Terminal 1: FastAPI server

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2: Worker

```bash
source .venv/bin/activate
python -m app.worker
```

Then open **http://localhost:8000** in your browser to use the web UI.

## API Endpoints

### `POST /api/prompt`

Submit a new prompt for AI processing.

**Request:**
```json
{
  "prompt_text": "Explain quantum computing in simple terms"
}
```

**Response:**
```json
{
  "prompt_id": "a1b2c3d4-...",
  "status": "pending",
  "message": "Prompt submitted successfully. Use /api/stream/{prompt_id} to stream the response."
}
```

### `GET /api/stream/{prompt_id}?last_id=0-0`

Stream the AI response via Server-Sent Events (SSE).

- Each token is sent as an SSE event with `event: token` and a Redis Stream `id` field.
- The stream ends with `event: done`.
- Use the `last_id` query parameter to resume streaming after a specific entry (e.g., after a page reload).

**SSE events:**
```
event: token
id: 1710412345678-0
data: Hello

event: token
id: 1710412345678-1
data:  world

event: done
data: [DONE]
```

### `GET /api/prompt/{prompt_id}`

Check the status of a prompt and retrieve the full response.

**Response:**
```json
{
  "prompt_id": "a1b2c3d4-...",
  "prompt_text": "Explain quantum computing",
  "status": "completed",
  "response": "Quantum computing is...",
  "error": null,
  "created_at": "2025-01-01T00:00:00",
  "updated_at": "2025-01-01T00:00:05"
}
```

### `GET /health`

Health check endpoint. Returns `{"status": "ok"}`.

## Features

- **Async everywhere** — FastAPI, SQLAlchemy, aio-pika, redis.asyncio, AsyncAzureOpenAI
- **Producer-consumer architecture** — API and AI processing are fully decoupled via RabbitMQ
- **Redis Streams** — token-by-token replay, TTL-based auto-cleanup, resume support
- **SSE streaming** — real-time token delivery to the browser
- **GPT-like UI** — fade-in token animation, blinking cursor, markdown stripping
- **Resume on reload** — client saves state to `sessionStorage` and resumes streaming from the last received token after a page reload
- **Graceful shutdown** — worker handles SIGINT/SIGTERM and cleans up connections

## How Resume-on-Reload Works

1. On every received token, the client saves `{ promptId, lastEventId, rawResponse, displayedLength }` to `sessionStorage`.
2. On page reload, the `pageshow` event fires and checks for saved state.
3. If found, it instantly renders the previously received text and reconnects to `/api/stream/{id}?last_id=<lastEventId>`.
4. The server reads the Redis Stream starting *after* the `last_id`, sending only the remaining tokens.
5. On stream completion, `sessionStorage` is cleared.
