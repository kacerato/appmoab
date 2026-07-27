"""
Modelo de Hidrômetro — Equipamento de medição vinculado a um cliente.

Cada hidrômetro possui um código único gravado no corpo do equipamento,
que é utilizado pelo GLM-OCR para associação automática via OCR.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Hydrometer(Base):
    __tablename__ = "hydrometers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Identificação ──────────────────────────────────────────
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    qr_code_token: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, default=lambda: f"AQMOAB-{uuid.uuid4().hex}")
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    red_digits: Mapped[int] = mapped_column(default=3, nullable=False)
    black_digits: Mapped[int | None] = mapped_column(default=None, nullable=True)

    # ── Localização ────────────────────────────────────────────
    location_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_radius_meters: Mapped[float] = mapped_column(Float, nullable=False, default=80.0)
    location_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    location_source: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── Última Leitura Registrada ──────────────────────────────
    last_reading_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_reading_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Status ─────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ─────────────────────────────────────────────
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────
    customer = relationship("Customer", back_populates="hydrometers")
    readings = relationship("Reading", back_populates="hydrometer", cascade="all, delete-orphan")
    reading_cycles = relationship("ReadingCycle", back_populates="hydrometer", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Hydrometer {self.code} (last: {self.last_reading_value} m³)>"
