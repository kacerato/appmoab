"""
Modelo de Fatura — Boleto gerado via Banco Inter.

Cada fatura pode ser:
- Vinculada a uma leitura (cliente COM hidrômetro)
- Sem leitura (cliente SEM hidrômetro, taxa fixa R$100)

Ciclo de vida: pending → sent → paid/overdue → cancelled
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import String, Float, Date, DateTime, ForeignKey, Text, Enum as SAEnum, LargeBinary
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reading_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("readings.id"), nullable=True, index=True
    )

    # ── Dados de Cálculo ───────────────────────────────────────
    consumption_m3: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tariff_rate: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    reference_month: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-05"

    # ── Datas ──────────────────────────────────────────────────
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Status ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "sent", "paid", "overdue", "cancelled", name="invoice_status_enum", create_constraint=True),
        nullable=False,
        default="pending",
        index=True,
    )

    # ── Dados do Banco Inter ───────────────────────────────────
    inter_codigo_solicitacao: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    inter_nosso_numero: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inter_linha_digitavel: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inter_codigo_barras: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inter_pix_copia_cola: Mapped[str | None] = mapped_column(Text, nullable=True)
    inter_raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── PDF do Boleto ──────────────────────────────────────────
    pdf_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

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
    customer = relationship("Customer", back_populates="invoices")
    reading = relationship("Reading", back_populates="invoice")
    notifications = relationship("Notification", back_populates="invoice", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Invoice R${self.amount:.2f} [{self.status}] due:{self.due_date}>"
