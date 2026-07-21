"""Amostras e rotulos do ciclo de aprendizagem da leitura visual."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VisionInference(Base):
    __tablename__ = "vision_inferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hydrometer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hydrometers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collaborator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="reading", index=True)
    original_object_key: Mapped[str | None] = mapped_column(String(700), nullable=True)
    rectified_object_key: Mapped[str | None] = mapped_column(String(700), nullable=True)
    frame_object_keys: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    capture_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    capture_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    predicted_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    predicted_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    auto_fill_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, default="confirm", index=True)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decoder_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    calibration_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quality: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    digits: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    alternatives: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    red_digits: Mapped[int | None] = mapped_column(nullable=True)
    black_digits: Mapped[int | None] = mapped_column(nullable=True)
    hydrometer_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hydrometer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confirmed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    approved_for_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    slot_labels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dataset_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    divergence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

