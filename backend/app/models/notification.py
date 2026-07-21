"""
Modelo de Notificação — Log de todas as comunicações enviadas.

Preparado para WhatsApp Cloud API (ativação futura via flag).
Registra tanto notificações enviadas quanto as que ficam em fila.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Canal e Tipo ───────────────────────────────────────────
    channel: Mapped[str] = mapped_column(
        SAEnum("whatsapp", "email", "sms", name="notification_channel_enum", create_constraint=True),
        nullable=False,
        default="whatsapp",
    )
    type: Mapped[str] = mapped_column(
        SAEnum(
            "reminder_5d", "due_today", "overdue_1d",
            "payment_confirmed", "invoice_generated", "custom",
            name="notification_type_enum",
            create_constraint=True,
        ),
        nullable=False,
    )

    # ── Status de Envio ────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum("queued", "sent", "failed", "delivered", "read", name="notification_status_enum", create_constraint=True),
        nullable=False,
        default="queued",
    )

    # ── Dados Externos ─────────────────────────────────────────
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # ── Timestamps ─────────────────────────────────────────────
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────
    customer = relationship("Customer", back_populates="notifications")
    invoice = relationship("Invoice", back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification {self.type} [{self.status}] → {self.channel}>"
