import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models import Prompt
from app.rabbitmq import publish_prompt
from app.redis_stream import read_stream, stream_exists
from app.schemas import PromptRequest, PromptResponse, PromptStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["prompts"])


@router.post("/prompt", response_model=PromptResponse)
async def submit_prompt(
    body: PromptRequest,
    db: AsyncSession = Depends(get_db),
):
    prompt = Prompt(
        prompt_text=body.prompt_text,
        status="pending",
    )
    db.add(prompt)
    await db.flush()
    prompt_id = prompt.id

    await publish_prompt(prompt_id=prompt_id, prompt_text=body.prompt_text)

    logger.info("Prompt '%s' submitted and queued", prompt_id)

    return PromptResponse(
        prompt_id=prompt_id,
        status="pending",
        message="Prompt submitted successfully. Use /api/stream/{prompt_id} to stream the response.",
    )


@router.get("/stream/{prompt_id}")
async def stream_response(
    prompt_id: str,
    last_id: str = Query(default="0-0"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' not found")

    redis_has_stream = await stream_exists(prompt_id)

    if redis_has_stream:
        async def _stream_generator():
            try:
                async for entry_id, token in read_stream(prompt_id, start_id=last_id):
                    yield {"event": "token", "id": entry_id, "data": token}
                yield {"event": "done", "data": "[DONE]"}
            except Exception as e:
                logger.exception("Error streaming prompt '%s'", prompt_id)
                yield {"event": "error", "data": str(e)}
                yield {"event": "done", "data": "[DONE]"}

        return EventSourceResponse(_stream_generator())

    if prompt.status == "completed" and prompt.response:
        async def _completed_generator():
            yield {"event": "token", "data": prompt.response}
            yield {"event": "done", "data": "[DONE]"}

        return EventSourceResponse(_completed_generator())

    if prompt.status == "failed":
        async def _error_generator():
            yield {"event": "error", "data": prompt.error or "Processing failed"}
            yield {"event": "done", "data": "[DONE]"}

        return EventSourceResponse(_error_generator())

    async def _waiting_generator():
        try:
            async for entry_id, token in read_stream(prompt_id, start_id=last_id):
                yield {"event": "token", "id": entry_id, "data": token}
            yield {"event": "done", "data": "[DONE]"}
        except Exception as e:
            logger.exception("Error streaming prompt '%s'", prompt_id)
            yield {"event": "error", "data": str(e)}
            yield {"event": "done", "data": "[DONE]"}

    return EventSourceResponse(_waiting_generator())


@router.get("/prompt/{prompt_id}", response_model=PromptStatusResponse)
async def get_prompt_status(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' not found")

    return PromptStatusResponse(
        prompt_id=prompt.id,
        prompt_text=prompt.prompt_text,
        status=prompt.status,
        response=prompt.response,
        error=prompt.error,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )
