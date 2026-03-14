import logging
from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

STREAM_PREFIX = "stream:"
STREAM_TTL_SECONDS = 300
DONE_TOKEN = "[DONE]"

_redis: aioredis.Redis | None = None


async def connect_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    await _redis.ping()
    logger.info("Connected to Redis at %s", settings.redis_url)


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        logger.info("Redis connection closed")
    _redis = None


def _stream_key(prompt_id: str) -> str:
    return f"{STREAM_PREFIX}{prompt_id}"


async def add_token(prompt_id: str, token: str) -> None:
    if _redis is None:
        raise RuntimeError("Redis is not initialized. Call connect_redis() first.")

    key = _stream_key(prompt_id)
    await _redis.xadd(key, {"token": token})


async def mark_done(prompt_id: str) -> None:
    if _redis is None:
        raise RuntimeError("Redis is not initialized. Call connect_redis() first.")

    key = _stream_key(prompt_id)
    await _redis.xadd(key, {"token": DONE_TOKEN})
    await _redis.expire(key, STREAM_TTL_SECONDS)
    logger.info("Marked stream '%s' as DONE with TTL=%ds", key, STREAM_TTL_SECONDS)


async def stream_exists(prompt_id: str) -> bool:
    if _redis is None:
        raise RuntimeError("Redis is not initialized. Call connect_redis() first.")

    key = _stream_key(prompt_id)
    return bool(await _redis.exists(key))


async def read_stream(
    prompt_id: str,
    block_ms: int = 100,
    start_id: str = "0-0",
) -> AsyncGenerator[tuple[str, str], None]:
    if _redis is None:
        raise RuntimeError("Redis is not initialized. Call connect_redis() first.")

    key = _stream_key(prompt_id)
    last_id = start_id

    while True:
        entries = await _redis.xread({key: last_id}, count=100, block=block_ms)

        if not entries:
            exists = await _redis.exists(key)
            if not exists:
                logger.warning("Stream '%s' does not exist (yet or expired)", key)
                continue
            continue

        for _stream_name, messages in entries:
            for entry_id, fields in messages:
                last_id = entry_id
                token = fields.get("token", "")

                if token == DONE_TOKEN:
                    logger.info("Received DONE signal for stream '%s'", key)
                    return

                yield entry_id, token
