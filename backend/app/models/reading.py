"""
Modelo de Leitura — Registro de medição do hidrômetro em campo.

Capturada pelo colaborador via app mobile com:
- Foto do hidrômetro
- GPS + timestamp
- OCR via GLM-OCR (código + leitura)

Fluxo: pending → approved/rejected
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Enum as SAEnum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hydrometer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hydrometers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collaborator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # ── Valores de Leitura ─────────────────────────────────────
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    previous_value: Mapped[float] = mapped_column(Float, nullable=False)
    consumption: Mapped[float] = mapped_column(Float, nullable=False)

    # ── Dados da Foto / OCR ────────────────────────────────────
    photo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_extracted_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_extracted_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Geolocalização da Captura ──────────────────────────────
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_from_hydrometer_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unchecked")
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    validation_flags: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    anomaly_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Fluxo de Aprovação ─────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "approved", "rejected", name="reading_status_enum", create_constraint=True),
        nullable=False,
        default="pending",
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Timestamps ─────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────
    hydrometer = relationship("Hydrometer", back_populates="readings")
    collaborator = relationship("User", back_populates="readings_captured", foreign_keys=[collaborator_id])
    approver = relationship("User", back_populates="readings_approved", foreign_keys=[approved_by])
    invoice = relationship("Invoice", back_populates="reading", uselist=False)

    def __repr__(self) -> str:
        return f"<Reading {self.consumption:.2f}m³ [{self.status}]>"
