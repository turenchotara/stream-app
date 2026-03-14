import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.database import close_db, init_db
from app.rabbitmq import close_rabbitmq, connect_rabbitmq
from app.redis_stream import close_redis, connect_redis
from app.routes.prompt import router as prompt_router

TEMPLATES_DIR = Path(__file__).parent / "templates"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — initializing connections...")

    await init_db()
    await connect_rabbitmq()
    await connect_redis()

    logger.info("All connections established. Application is ready.")

    yield

    logger.info("Shutting down — closing connections...")
    await close_rabbitmq()
    await close_redis()
    await close_db()
    logger.info("All connections closed. Goodbye.")


app = FastAPI(
    title="AI Streaming API",
    description=(
        "A reliable AI streaming API built with FastAPI, RabbitMQ, Redis Streams, and MySQL. "
        "Submit prompts to be processed asynchronously and stream responses via SSE."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prompt_router)


@app.get("/", response_class=HTMLResponse, tags=["ui"])
async def serve_ui():
    html_path = TEMPLATES_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}
