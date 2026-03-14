import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt_text = Column(Text, nullable=False)
    status = Column(
        Enum("pending", "processing", "completed", "failed", name="prompt_status"),
        nullable=False,
        default="pending",
    )
    response = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Prompt(id={self.id}, status={self.status})>"
