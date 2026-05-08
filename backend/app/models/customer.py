"""
Modelo de Cliente — Clientes da distribuição de água.

Suporta dois tipos:
- COM hidrômetro: faturamento por consumo medido
- SEM hidrômetro: taxa fixa mensal (R$100)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, Integer, Enum as SAEnum, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Dados Pessoais ─────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cpf_cnpj: Mapped[str] = mapped_column(String(18), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Endereço ───────────────────────────────────────────────
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False, default="S/N")
    complement: Mapped[str | None] = mapped_column(String(255), nullable=True)
    neighborhood: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)

    # ── Configuração de Faturamento ────────────────────────────
    due_day: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    has_hydrometer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Status ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum("active", "suspended", "disconnected", name="customer_status_enum", create_constraint=True),
        nullable=False,
        default="active",
    )

    # ── Observações ────────────────────────────────────────────
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    # ── Relationships ──────────────────────────────────────────
    hydrometers = relationship("Hydrometer", back_populates="customer", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="customer", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="customer", cascade="all, delete-orphan")
    attachments = relationship("CustomerAttachment", back_populates="customer", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        meter = "COM" if self.has_hydrometer else "SEM"
        return f"<Customer {self.name} ({meter} hidrômetro) [{self.status}]>"
