"""Memoria operacional dos vereditos do Kimi Vision."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KimiVisionMemory(Base):
    __tablename__ = "kimi_vision_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hydrometer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hydrometers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collaborator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    predicted_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    predicted_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    confirmed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    red_digits: Mapped[int | None] = mapped_column(nullable=True)
    black_digits: Mapped[int | None] = mapped_column(nullable=True)
    hydrometer_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hydrometer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    divergence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
