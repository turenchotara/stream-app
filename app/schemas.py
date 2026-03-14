from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PromptRequest(BaseModel):
    prompt_text: str


class PromptResponse(BaseModel):
    prompt_id: str
    status: str
    message: str


class PromptStatusResponse(BaseModel):
    prompt_id: str
    prompt_text: str
    status: str
    response: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
