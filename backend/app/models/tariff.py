"""
Modelo de Faixa de Tarifa — Tabela de preços por faixa de consumo.

Totalmente configurável pelo painel admin.
A tarifa é aplicada sobre TODO o consumo (não apenas excedente).
Taxa mínima padrão: R$110.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, Integer, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TariffTier(Base):
    __tablename__ = "tariff_tiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Faixa de Consumo ───────────────────────────────────────
    label: Mapped[str] = mapped_column(String(100), nullable=False)  # "Até 10 m³"
    min_m3: Mapped[float] = mapped_column(Float, nullable=False)
    max_m3: Mapped[float] = mapped_column(Float, nullable=False)
    rate_per_m3: Mapped[float] = mapped_column(Float, nullable=False)

    # ── Taxa Mínima ────────────────────────────────────────────
    minimum_charge: Mapped[float] = mapped_column(Float, nullable=False, default=110.0)

    # ── Taxa Fixa (clientes sem hidrômetro) ────────────────────
    fixed_rate: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)

    # ── Ordenação ──────────────────────────────────────────────
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Status ─────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Timestamps ─────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TariffTier {self.label}: R${self.rate_per_m3}/m³>"
