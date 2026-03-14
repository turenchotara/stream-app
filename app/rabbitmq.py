import json
import logging
from typing import Any, Callable, Coroutine

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT_QUEUE = "prompts"

_connection: AbstractRobustConnection | None = None
_channel: aio_pika.abc.AbstractChannel | None = None


async def connect_rabbitmq() -> None:
    global _connection, _channel

    _connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    _channel = await _connection.channel()
    await _channel.set_qos(prefetch_count=1)

    await _channel.declare_queue(PROMPT_QUEUE, durable=True)

    logger.info("Connected to RabbitMQ and declared queue '%s'", PROMPT_QUEUE)


async def close_rabbitmq() -> None:
    global _connection, _channel
    if _connection and not _connection.is_closed:
        await _connection.close()
        logger.info("RabbitMQ connection closed")
    _connection = None
    _channel = None


async def publish_prompt(prompt_id: str, prompt_text: str) -> None:
    if _channel is None:
        raise RuntimeError("RabbitMQ channel is not initialized. Call connect_rabbitmq() first.")

    message_body = json.dumps({
        "prompt_id": prompt_id,
        "prompt_text": prompt_text,
    })

    message = Message(
        body=message_body.encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )

    await _channel.default_exchange.publish(
        message,
        routing_key=PROMPT_QUEUE,
    )

    logger.info("Published prompt '%s' to queue '%s'", prompt_id, PROMPT_QUEUE)


async def consume_prompts(
    callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
) -> None:
    if _channel is None:
        raise RuntimeError("RabbitMQ channel is not initialized. Call connect_rabbitmq() first.")

    queue = await _channel.declare_queue(PROMPT_QUEUE, durable=True)

    async def _on_message(message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=True):
            try:
                body = json.loads(message.body.decode("utf-8"))
                logger.info("Consumed prompt '%s' from queue", body.get("prompt_id"))
                await callback(body)
            except Exception:
                logger.exception("Error processing message, will be requeued")
                raise

    await queue.consume(_on_message)
    logger.info("Started consuming from queue '%s'", PROMPT_QUEUE)
