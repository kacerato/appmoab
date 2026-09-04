"""Fila idempotente de envio de faturas pelo WhatsApp."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.config import get_settings
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
DISPATCH_ADVISORY_LOCK_ID = 742_260_721
runtime_settings = get_settings()


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


def invoice_whatsapp_block_reason(invoice: Invoice) -> tuple[str, str] | None:
    """Validação compartilhada pela seleção manual e pela entrega da fila."""
    if invoice.status not in {"pending", "sent", "overdue"}:
        return "invoice_closed", "Fatura paga ou cancelada não pode ser enviada."
    if invoice.efi_status in {"identified", "approved", "paid", "settled", "canceled", "cancelled"}:
        return "charge_unavailable", "Cobrança com pagamento identificado ou encerrada na Efí."
    if invoice.reading_id and (not invoice.reading or invoice.reading.status != "approved"):
        return "reading_not_approved", "A leitura vinculada precisa estar aprovada."
    if not invoice.customer or not invoice.customer.phone:
        return "phone_missing", "Cliente sem telefone cadastrado."
    if len(whatsapp_service.normalize_phone(invoice.customer.phone)) not in {12, 13}:
        return "phone_invalid", "Telefone incompleto ou inválido para WhatsApp."
    if not invoice.efi_charge_id and not invoice.efi_payment_url:
        return "boleto_missing", "A fatura ainda não possui cobrança emitida na Efí."
    return None


async def enqueue_invoice_whatsapp(
    db: AsyncSession,
    invoice: Invoice,
    *,
    source: str,
    force: bool = False,
    manual: bool = False,
    requested_by: uuid.UUID | None = None,
) -> Notification | None:
    """Cria ou reaproveita uma unica entrega para a fatura."""
    settings = await _settings(db)
    if not manual and not notification_flow_enabled(settings, "invoice_generated"):
        return None

    # A notificação pode ainda não existir. Trave a fatura para serializar também
    # essa primeira inserção entre o botão manual e a aprovação automática.
    await db.execute(select(Invoice.id).where(Invoice.id == invoice.id).with_for_update())
    key = _idempotency_key(invoice.id)
    existing = (
        await db.execute(select(Notification).where(Notification.idempotency_key == key).with_for_update())
    ).scalar_one_or_none()
    if existing:
        if existing.status in {"sent", "delivered", "read"} and not force:
            return existing
        if existing.attempt_count >= MAX_ATTEMPTS and not force:
            return existing
        if manual:
            existing.payload = {
                **(existing.payload or {}), "manual_requested": True,
                "source": source, "requested_by": str(requested_by) if requested_by else None,
            }
        # Repetir o clique não antecipa backoff, limite de frequência ou pausa.
        if existing.next_attempt_at is not None and not force:
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
        payload={
            "flow_key": "invoice_generated", "source": source, "mode": "pending",
            "manual_requested": manual,
            "requested_by": str(requested_by) if requested_by else None,
        },
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


def _schedule_operational_wait(notification: Notification, detail: str, *, delay_seconds: int) -> None:
    """Mantém a entrega na fila quando o canal está indisponível, sem exibir falha técnica."""
    notification.status = "queued"
    notification.error_message = detail[:500]
    notification.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=max(delay_seconds, 30))


async def _reserve_dispatch_slot(db: AsyncSession) -> tuple[bool, str | None]:
    """Serializa os envios e limita rajadas mesmo com vários workers."""
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        acquired = (await db.execute(select(func.pg_try_advisory_xact_lock(DISPATCH_ADVISORY_LOCK_ID)))).scalar()
        if acquired is False:
            return False, "Outro envio já está em andamento. Esta fatura continua na fila."

    paused_until = (await db.execute(
        select(func.max(Notification.next_attempt_at)).where(
            Notification.channel == "whatsapp",
            Notification.payload["pause_reason"].as_string() == "account_restricted",
            Notification.next_attempt_at > datetime.now(timezone.utc),
        )
    )).scalar()
    if paused_until:
        return False, "Conta temporariamente restrita. Novos envios também aguardam a pausa de segurança."

    limit = max(int(runtime_settings.whatsapp_invoice_rate_limit_per_minute), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
    recent = (
        await db.execute(
            select(func.count())
            .select_from(WhatsAppMessage)
            .where(
                WhatsAppMessage.direction == "outbound",
                WhatsAppMessage.created_at >= cutoff,
            )
        )
    ).scalar() or 0
    if recent >= limit:
        return False, f"Limite seguro de {limit} envios por minuto atingido. Esta fatura continua na fila."
    return True, None


async def _customer_interval_available(db: AsyncSession, customer_id: uuid.UUID) -> tuple[bool, datetime | None]:
    """Evita mensagens automaticas repetidas para o mesmo cliente em curto intervalo."""
    interval = max(int(runtime_settings.whatsapp_customer_min_interval_minutes), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=interval)
    last_sent = (
        await db.execute(
            select(func.max(WhatsAppMessage.created_at)).where(
                WhatsAppMessage.customer_id == customer_id,
                WhatsAppMessage.direction == "outbound",
                WhatsAppMessage.created_at >= cutoff,
            )
        )
    ).scalar()
    if not last_sent:
        return True, None
    return False, last_sent + timedelta(minutes=interval)


async def _pause_whatsapp_queue(db: AsyncSession, *, until: datetime, detail: str) -> None:
    """Pausa toda a fila quando o provedor sinaliza restricao da conta."""
    await db.execute(
        update(Notification)
        .where(
            Notification.channel == "whatsapp",
            Notification.status.in_(("queued", "failed")),
        )
        .values(status="queued", error_message=detail[:500], next_attempt_at=until)
    )


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
            .options(selectinload(Invoice.customer), selectinload(Invoice.reading))
            .where(Invoice.id == notification.invoice_id)
        )
    ).scalar_one_or_none()
    if not invoice or not invoice.customer:
        notification.attempt_count = MAX_ATTEMPTS
        _schedule_retry(notification, "Fatura ou cliente nao encontrado.")
        return {"status": "failed", "reason": "invoice_missing", "detail": notification.error_message}
    blocked = invoice_whatsapp_block_reason(invoice)
    if blocked:
        notification.status = "failed"
        notification.error_message = blocked[1]
        notification.next_attempt_at = None
        return {"status": "failed", "reason": blocked[0], "detail": blocked[1]}

    if notification.next_attempt_at and notification.next_attempt_at > datetime.now(timezone.utc) and not force:
        return {
            "status": "queued", "reason": "scheduled",
            "detail": notification.error_message or "Envio agendado na fila segura.",
        }

    source = str((notification.payload or {}).get("source") or "invoice_dispatch")

    settings = await _settings(db)
    if not (notification.payload or {}).get("manual_requested") and not notification_flow_enabled(settings, "invoice_generated"):
        notification.status = "failed"
        notification.error_message = "Fluxo de fatura desativado nas configuracoes."
        notification.next_attempt_at = None
        return {"status": "failed", "reason": "flow_disabled", "detail": notification.error_message}

    health = await whatsapp_service.health()
    if not health["connected"]:
        detail = "WhatsApp desconectado. Conecte o número pelo QR Code no dashboard; a fatura continuará na fila."
        _schedule_operational_wait(notification, detail, delay_seconds=300)
        return {"status": "queued", "reason": "whatsapp_disconnected", "detail": detail}

    slot_available, rate_detail = await _reserve_dispatch_slot(db)
    if not slot_available:
        detail = rate_detail or "Envio adiado para evitar uma rajada de mensagens."
        _schedule_operational_wait(notification, detail, delay_seconds=75)
        return {"status": "queued", "reason": "local_rate_limit", "detail": detail}

    customer_available, customer_next_at = await _customer_interval_available(db, invoice.customer_id)
    if not customer_available:
        detail = "Envio adiado para evitar mensagens repetidas ao mesmo cliente."
        notification.status = "queued"
        notification.error_message = detail
        notification.next_attempt_at = customer_next_at
        return {"status": "queued", "reason": "customer_frequency_limit", "detail": detail}

    notification.attempt_count += 1
    notification.last_attempt_at = datetime.now(timezone.utc)

    message = render_invoice_customer_message(
        settings,
        charge_type=invoice.charge_type,
        customer_name=invoice.customer.name,
        amount=invoice.amount,
        due_date=invoice.payment_due_date or invoice.due_date,
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
        error_code = str((result or {}).get("error_code") or "dispatch_failed")
        detail = str((result or {}).get("error") or "O WhatsApp não confirmou o envio agora.")
        if error_code in {"account_restricted", "rate_limited", "whatsapp_disconnected"}:
            detail = f"{detail.rstrip()} A fatura continuará na fila."
            notification.attempt_count = max(notification.attempt_count - 1, 0)
            if error_code == "account_restricted":
                delay_seconds = max(runtime_settings.whatsapp_restriction_cooldown_minutes, 60) * 60
            elif error_code == "rate_limited":
                delay_seconds = 15 * 60
            else:
                delay_seconds = 5 * 60
            _schedule_operational_wait(notification, detail, delay_seconds=delay_seconds)
            if error_code == "account_restricted":
                notification.payload = {**(notification.payload or {}), "pause_reason": error_code}
                await _pause_whatsapp_queue(
                    db,
                    until=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
                    detail=detail,
                )
            notification.payload = {**(notification.payload or {}), "mode": mode, "message": message}
            return {"status": "queued", "reason": error_code, "detail": detail}
        _schedule_retry(notification, detail)
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
                .limit(max(int(runtime_settings.whatsapp_invoice_batch_size), 1))
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
