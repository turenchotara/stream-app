import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any

from openai import AsyncAzureOpenAI
from sqlalchemy import update

from app.config import settings
from app.database import async_session_factory, close_db, init_db
from app.models import Prompt
from app.rabbitmq import close_rabbitmq, connect_rabbitmq, consume_prompts
from app.redis_stream import add_token, close_redis, connect_redis, mark_done

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

openai_client = AsyncAzureOpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
)

shutdown_event = asyncio.Event()


async def update_prompt_status(
    prompt_id: str,
    status: str,
    response: str | None = None,
    error: str | None = None,
) -> None:
    async with async_session_factory() as session:
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if response is not None:
            values["response"] = response
        if error is not None:
            values["error"] = error

        await session.execute(
            update(Prompt).where(Prompt.id == prompt_id).values(**values)
        )
        await session.commit()


async def process_prompt(message: dict[str, Any]) -> None:
    prompt_id = message["prompt_id"]
    prompt_text = message["prompt_text"]

    logger.info("Processing prompt '%s': %s", prompt_id, prompt_text[:80])

    await update_prompt_status(prompt_id, "processing")

    try:
        stream = await openai_client.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt_text},
            ],
            stream=True,
        )

        full_response = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                token = delta.content
                full_response += token
                await add_token(prompt_id, token)

        await mark_done(prompt_id)

        await update_prompt_status(prompt_id, "completed", response=full_response)

        logger.info(
            "Prompt '%s' completed. Response length: %d chars",
            prompt_id,
            len(full_response),
        )

    except Exception as e:
        logger.exception("Error processing prompt '%s'", prompt_id)

        try:
            await add_token(prompt_id, f"[ERROR] {str(e)}")
            await mark_done(prompt_id)
        except Exception:
            logger.exception("Failed to write error to Redis for prompt '%s'", prompt_id)

        await update_prompt_status(prompt_id, "failed", error=str(e))

        raise


async def main() -> None:
    logger.info("Starting worker...")

    await init_db()
    await connect_rabbitmq()
    await connect_redis()

    logger.info("Worker is ready. Waiting for prompts...")

    await consume_prompts(process_prompt)

    await shutdown_event.wait()

    logger.info("Shutting down worker...")
    await close_rabbitmq()
    await close_redis()
    await close_db()
    logger.info("Worker stopped.")


def _handle_signal() -> None:
    logger.info("Received shutdown signal")
    shutdown_event.set()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
