"""
Modelo de Hidrômetro — Equipamento de medição vinculado a um cliente.

Cada hidrômetro possui um código único gravado no corpo do equipamento,
que é utilizado pelo Kimi K2.6 para associação automática via OCR.
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
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Localização ────────────────────────────────────────────
    location_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Última Leitura Registrada ──────────────────────────────
    last_reading_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_reading_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Status ─────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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

    def __repr__(self) -> str:
        return f"<Hydrometer {self.code} (last: {self.last_reading_value} m³)>"
