"""Fila idempotente de envio de faturas pelo WhatsApp."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.models.invoice_event import InvoiceEvent
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.models.whatsapp_message import WhatsAppMessage
from app.services.efi_api import efi_service
from app.services.invoice_documents import get_or_create_boleto_pdf
from app.services.notification_templates import (
    FLOW_NOTIFICATION_TYPES,
    notification_flow_enabled,
    render_invoice_customer_message,
)
from app.services.whatsapp_api import whatsapp_service

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAYS_MINUTES = (2, 5, 15, 60, 180)


async def _settings(db: AsyncSession) -> SystemSetting:
    item = (await db.execute(select(SystemSetting).where(SystemSetting.id == 1))).scalar_one_or_none()
    if item:
        return item
    item = SystemSetting(id=1)
    db.add(item)
    await db.flush()
    return item


def _idempotency_key(invoice_id: uuid.UUID) -> str:
    return f"invoice:{invoice_id}:invoice_generated:whatsapp"


async def enqueue_invoice_whatsapp(
    db: AsyncSession,
    invoice: Invoice,
    *,
    source: str,
    force: bool = False,
) -> Notification | None:
    """Cria ou reaproveita uma unica entrega para a fatura."""
    settings = await _settings(db)
    if not notification_flow_enabled(settings, "invoice_generated"):
        return None

    key = _idempotency_key(invoice.id)
    existing = (
        await db.execute(select(Notification).where(Notification.idempotency_key == key).with_for_update())
    ).scalar_one_or_none()
    if existing:
        if existing.status in {"sent", "delivered", "read"} and not force:
            return existing
        if existing.attempt_count >= MAX_ATTEMPTS and not force:
            return existing
        existing.status = "queued"
        existing.error_message = None
        existing.next_attempt_at = datetime.now(timezone.utc)
        existing.payload = {**(existing.payload or {}), "source": source, "manual_retry": force}
        return existing

    notification = Notification(
        customer_id=invoice.customer_id,
        invoice_id=invoice.id,
        channel="whatsapp",
        type=FLOW_NOTIFICATION_TYPES["invoice_generated"],
        status="queued",
        idempotency_key=key,
        attempt_count=0,
        next_attempt_at=datetime.now(timezone.utc),
        payload={"flow_key": "invoice_generated", "source": source, "mode": "pending"},
    )
    db.add(notification)
    await db.flush()
    return notification


def _schedule_retry(notification: Notification, error: str) -> None:
    notification.status = "failed"
    notification.error_message = error[:500]
    if notification.attempt_count < MAX_ATTEMPTS:
        delay_index = min(max(notification.attempt_count - 1, 0), len(RETRY_DELAYS_MINUTES) - 1)
        notification.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=RETRY_DELAYS_MINUTES[delay_index])
    else:
        notification.next_attempt_at = None


def _event(db: AsyncSession, invoice: Invoice, sent: bool, notification: Notification, *, mode: str, source: str) -> None:
    db.add(InvoiceEvent(
        invoice_id=invoice.id,
        event_type="whatsapp_invoice_sent" if sent else "whatsapp_invoice_failed",
        previous_status=invoice.status,
        new_status=invoice.status,
        reason=notification.error_message,
        payload={
            "mode": mode,
            "message_id": notification.external_message_id,
            "source": source,
            "attempt": notification.attempt_count,
            "notification_id": str(notification.id),
        },
    ))


async def dispatch_invoice_notification(
    db: AsyncSession,
    notification_id: uuid.UUID,
    *,
    force: bool = False,
) -> dict:
    notification = (
        await db.execute(
            select(Notification)
            .where(Notification.id == notification_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not notification:
        return {"status": "failed", "reason": "notification_missing", "detail": "Envio nao encontrado."}
    if notification.status in {"sent", "delivered", "read"} and not force:
        return {"status": "sent", "reason": "already_sent", "detail": "A fatura ja foi enviada pelo WhatsApp."}
    if notification.attempt_count >= MAX_ATTEMPTS and not force:
        return {"status": "failed", "reason": "retry_exhausted", "detail": "O limite automatico de tentativas foi atingido."}

    invoice = (
        await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.customer))
            .where(Invoice.id == notification.invoice_id)
        )
    ).scalar_one_or_none()
    if not invoice or not invoice.customer:
        notification.attempt_count = MAX_ATTEMPTS
        _schedule_retry(notification, "Fatura ou cliente nao encontrado.")
        return {"status": "failed", "reason": "invoice_missing", "detail": notification.error_message}
    if invoice.status == "cancelled":
        notification.status = "failed"
        notification.error_message = "Fatura cancelada nao pode ser enviada."
        notification.attempt_count = MAX_ATTEMPTS
        notification.next_attempt_at = None
        return {"status": "failed", "reason": "invoice_cancelled", "detail": notification.error_message}

    notification.attempt_count += 1
    notification.last_attempt_at = datetime.now(timezone.utc)
    source = str((notification.payload or {}).get("source") or "invoice_dispatch")
    if not invoice.customer.phone:
        _schedule_retry(notification, "Cliente sem telefone cadastrado.")
        notification.next_attempt_at = None
        _event(db, invoice, False, notification, mode="phone_missing", source=source)
        return {"status": "failed", "reason": "phone_missing", "detail": notification.error_message}
    if len(whatsapp_service.normalize_phone(invoice.customer.phone)) < 12:
        _schedule_retry(notification, "Telefone incompleto ou invalido para WhatsApp.")
        notification.next_attempt_at = None
        _event(db, invoice, False, notification, mode="phone_invalid", source=source)
        return {"status": "failed", "reason": "phone_invalid", "detail": notification.error_message}
    if not invoice.efi_charge_id and not invoice.efi_payment_url:
        _schedule_retry(notification, "A fatura ainda nao possui cobranca emitida na Efi.")
        _event(db, invoice, False, notification, mode="boleto_missing", source=source)
        return {"status": "failed", "reason": "boleto_missing", "detail": notification.error_message}

    settings = await _settings(db)
    if not notification_flow_enabled(settings, "invoice_generated"):
        notification.status = "failed"
        notification.error_message = "Fluxo de fatura desativado nas configuracoes."
        notification.next_attempt_at = None
        return {"status": "failed", "reason": "flow_disabled", "detail": notification.error_message}

    health = await whatsapp_service.health()
    if not health["connected"]:
        detail = f"Instancia Evolution desconectada ({health['instance_state']})."
        _schedule_retry(notification, detail)
        _event(db, invoice, False, notification, mode="connection_check", source=source)
        return {"status": "failed", "reason": "whatsapp_disconnected", "detail": detail}

    message = render_invoice_customer_message(
        settings,
        charge_type=invoice.charge_type,
        customer_name=invoice.customer.name,
        amount=invoice.amount,
        due_date=invoice.due_date,
        reference_month=invoice.reference_month,
    )
    if invoice.efi_payment_url and invoice.efi_payment_url not in message:
        message = f"{message}\n\nLink de pagamento: {invoice.efi_payment_url}"

    mode = "payment_link"
    try:
        pdf_data = await get_or_create_boleto_pdf(
            db,
            invoice,
            efi_service.baixar_pdf,
            source="whatsapp_dispatch",
        )
        if pdf_data:
            mode = "document"
            result = await whatsapp_service.send_invoice_document(
                phone=invoice.customer.phone,
                pdf_data=pdf_data,
                filename=f"boleto_{str(invoice.id)[:8]}.pdf",
                caption=message,
            )
        elif invoice.efi_payment_url:
            result = await whatsapp_service.send_text(invoice.customer.phone, message)
        else:
            result = {"status": "failed", "error": "Fatura sem PDF e sem link de pagamento."}
    except Exception as exc:
        logger.warning("Falha no envio WhatsApp da fatura %s: %s", invoice.id, exc)
        result = {"status": "failed", "error": str(exc)}

    if not result or result.get("status") != "sent":
        _schedule_retry(notification, str((result or {}).get("error") or "Evolution nao confirmou o envio."))
        notification.payload = {**(notification.payload or {}), "mode": mode, "message": message}
        _event(db, invoice, False, notification, mode=mode, source=source)
        return {"status": "failed", "reason": "dispatch_failed", "detail": notification.error_message}

    notification.status = "sent"
    notification.external_message_id = result.get("message_id")
    notification.error_message = None
    notification.sent_at = datetime.now(timezone.utc)
    notification.next_attempt_at = None
    notification.payload = {**(notification.payload or {}), "mode": mode, "message": message}
    db.add(WhatsAppMessage(
        customer_id=invoice.customer_id,
        phone=whatsapp_service.normalize_phone(invoice.customer.phone),
        direction="outbound",
        body=message,
        external_message_id=notification.external_message_id,
        status="sent",
        payload={"flow_key": "invoice_generated", "invoice_id": str(invoice.id), "mode": mode},
    ))
    _event(db, invoice, True, notification, mode=mode, source=source)
    return {"status": "sent", "reason": "ok", "detail": "Fatura enviada pelo WhatsApp."}


async def dispatch_invoice_notification_task(notification_id: str) -> None:
    """Primeira tentativa apos o commit da operacao que criou a fatura."""
    await asyncio.sleep(0.5)
    async with async_session_factory() as db:
        try:
            await dispatch_invoice_notification(db, uuid.UUID(notification_id))
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Falha inesperada ao processar notificacao %s", notification_id)


async def dispatch_due_invoice_notifications() -> int:
    """Reprocessa entregas pendentes; chamada pelo Celery Beat."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        ids = (
            await db.execute(
                select(Notification.id)
                .where(
                    Notification.channel == "whatsapp",
                    Notification.type == FLOW_NOTIFICATION_TYPES["invoice_generated"],
                    Notification.status.in_(["queued", "failed"]),
                    Notification.attempt_count < MAX_ATTEMPTS,
                    Notification.next_attempt_at.is_not(None),
                    Notification.next_attempt_at <= now,
                )
                .order_by(Notification.created_at)
                .limit(50)
            )
        ).scalars().all()

    processed = 0
    for notification_id in ids:
        async with async_session_factory() as db:
            try:
                await dispatch_invoice_notification(db, notification_id)
                await db.commit()
                processed += 1
            except Exception:
                await db.rollback()
                logger.exception("Falha no retry da notificacao %s", notification_id)
    return processed
