"""
AquaMoab — Webhooks Router.
Recebe requisições de serviços externos, como o nosso microserviço de WhatsApp.
"""

from datetime import datetime

from fastapi import APIRouter, Request, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database import get_db
from app.config import get_settings
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.reading_cycle import ReadingCycle
from app.models.invoice_event import InvoiceEvent
from app.models.whatsapp_message import WhatsAppMessage
from app.services.efi_api import efi_service
from app.services.payment_receipts import store_efi_payment_receipt
from app.services.whatsapp_api import whatsapp_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _require_webhook_secret(request: Request) -> None:
    if not settings.webhook_shared_secret:
        return

    provided = request.headers.get("x-aquamoab-webhook-secret") or request.query_params.get("secret")
    if provided != settings.webhook_shared_secret:
        raise HTTPException(status_code=401, detail="Webhook nao autorizado")


def _normalize_evolution_event(event: str | None) -> str:
    return (event or "").strip().lower().replace("_", ".")


def _event_items(payload: dict) -> list[dict]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _message_key(data: dict) -> dict:
    key = data.get("key") or {}
    return key if isinstance(key, dict) else {}


def _message_id(data: dict) -> str | None:
    key = _message_key(data)
    value = key.get("id") or data.get("messageId") or data.get("id")
    return str(value) if value else None


def _remote_jid(data: dict) -> str:
    key = _message_key(data)
    return str(key.get("remoteJid") or data.get("remoteJid") or data.get("jid") or "")


def _normalize_webhook_phone(remote_jid: str) -> str:
    raw_phone = remote_jid.split("@", 1)[0]
    return whatsapp_service.normalize_phone(raw_phone)


def _from_me(data: dict) -> bool:
    key = _message_key(data)
    return bool(key.get("fromMe") or data.get("fromMe"))


def _text_from_nested(value: object, *keys: str) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _extract_message_body(data: dict) -> str:
    message_obj = data.get("message") or {}
    if not isinstance(message_obj, dict):
        return ""

    direct = _text_from_nested(message_obj, "conversation")
    if direct:
        return direct

    nested_text_sources = (
        ("extendedTextMessage", "text"),
        ("imageMessage", "caption"),
        ("videoMessage", "caption"),
        ("documentMessage", "caption"),
        ("buttonsResponseMessage", "selectedDisplayText", "selectedButtonId"),
        ("templateButtonReplyMessage", "selectedDisplayText", "selectedId"),
        ("listResponseMessage", "title", "description"),
        ("reactionMessage", "text"),
    )
    for source_key, *text_keys in nested_text_sources:
        text = _text_from_nested(message_obj.get(source_key), *text_keys)
        if text:
            return text

    document_name = _text_from_nested(message_obj.get("documentMessage"), "fileName")
    if document_name:
        return f"Documento recebido: {document_name}"
    if "audioMessage" in message_obj:
        return "Audio recebido"
    if "imageMessage" in message_obj:
        return "Imagem recebida"
    if "videoMessage" in message_obj:
        return "Video recebido"
    if "stickerMessage" in message_obj:
        return "Figurinha recebida"
    return ""


def _map_delivery_status(status_value: object) -> str | None:
    if status_value is None:
        return None
    status = str(status_value).strip().lower()
    status = status.replace("-", "_").replace(" ", "_")
    status_map = {
        "read": "read",
        "played": "read",
        "read_ack": "read",
        "delivery_ack": "delivered",
        "delivered": "delivered",
        "server_ack": "sent",
        "sent": "sent",
        "pending": "sent",
        "error": "failed",
        "failed": "failed",
    }
    return status_map.get(status)


def _status_from_data(data: dict) -> str | None:
    update = data.get("update")
    status = data.get("status") or data.get("ack") or data.get("messageStatus") or data.get("deliveryStatus")
    if not status and isinstance(update, dict):
        status = update.get("status") or update.get("ack")
    return _map_delivery_status(status)


async def _find_customer_for_phone(db: AsyncSession, phone: str) -> Customer | None:
    digits = "".join(char for char in phone if char.isdigit())
    if len(digits) < 8:
        return None

    result = await db.execute(
        select(Customer)
        .where(Customer.phone.is_not(None), Customer.phone.ilike(f"%{digits[-8:]}%"))
        .order_by(Customer.name)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _update_message_status(db: AsyncSession, data: dict, payload: dict) -> bool:
    message_id = _message_id(data)
    status = _status_from_data(data)
    if not message_id or not status:
        return False

    result = await db.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.external_message_id == message_id).limit(1)
    )
    message = result.scalar_one_or_none()
    if not message:
        logger.info("Status WhatsApp sem mensagem local: id=%s status=%s", message_id, status)
        return False

    message.status = status
    message.payload = {
        **(message.payload or {}),
        "status_webhook": payload,
    }
    await db.flush()
    logger.info("Status WhatsApp atualizado: id=%s status=%s", message_id, status)
    return True


def _map_efi_status(status: str | None, invoice: Invoice) -> str:
    if status in ("paid", "settled"):
        return "paid"
    if status in ("canceled", "refunded"):
        return "cancelled"
    if status in ("unpaid", "expired"):
        return "overdue"
    if status in ("waiting", "identified", "approved", "link"):
        return "sent"
    return invoice.status


@router.post("/efi")
async def efi_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Recebe token de notificacao da Efí, consulta detalhes e atualiza fatura."""
    _require_webhook_secret(request)
    content_type = request.headers.get("content-type", "")
    notification_token = None
    if "application/json" in content_type:
        payload = await request.json()
        notification_token = payload.get("notification")
    else:
        form = await request.form()
        notification_token = form.get("notification")

    if not notification_token:
        return {"status": "ignored", "reason": "missing_notification_token"}

    detail = await efi_service.consultar_por_notificacao(str(notification_token))
    events = detail.get("data") or []
    if not events:
        return {"status": "ignored", "reason": "empty_notification"}

    latest = events[-1]
    charge_id = str((latest.get("identifiers") or {}).get("charge_id") or "")
    current_status = (latest.get("status") or {}).get("current")
    if not charge_id:
        return {"status": "ignored", "reason": "missing_charge_id"}

    result = await db.execute(select(Invoice).where(Invoice.efi_charge_id == charge_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        return {"status": "ignored", "reason": "invoice_not_found", "charge_id": charge_id}

    previous_status = invoice.status
    invoice.efi_status = current_status
    invoice.efi_raw_response = detail
    mapped_status = _map_efi_status(current_status, invoice)
    invoice.status = mapped_status
    if invoice.cycle_id and mapped_status in {"paid", "cancelled"}:
        cycle = await db.get(ReadingCycle, invoice.cycle_id)
        if cycle:
            cycle.status = "paid" if mapped_status == "paid" else "invoice_cancelled"
    if mapped_status == "paid":
        received_at = latest.get("received_by_bank_at") or latest.get("created_at")
        try:
            invoice.paid_date = datetime.fromisoformat(str(received_at)[:10]).date()
        except ValueError:
            from datetime import date
            invoice.paid_date = date.today()
        invoice.efi_payment_receipt_url = await store_efi_payment_receipt(db, invoice, detail)

    db.add(InvoiceEvent(
        invoice_id=invoice.id,
        event_type="efi_webhook_applied",
        previous_status=previous_status,
        new_status=invoice.status,
        reason="Webhook Efí atualizou a fatura",
        payload={
            "charge_id": charge_id,
            "efi_status": current_status,
            "notification": str(notification_token),
            "was_locally_cancelled": previous_status == "cancelled" and mapped_status == "paid",
        },
    ))
    await db.flush()
    logger.info("Notificacao Efí aplicada na fatura %s: %s", invoice.id, current_status)
    return {"status": "ok", "invoice_id": str(invoice.id), "efi_status": current_status}


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Recebe mensagens do microserviço Evolution API.
    """
    _require_webhook_secret(request)
    try:
        payload = await request.json()
        event = _normalize_evolution_event(payload.get("event"))
        items = _event_items(payload)

        if event in {"messages.update", "message.update", "messages.status", "message.status"}:
            updated = 0
            for data in items:
                if await _update_message_status(db, data, payload):
                    updated += 1
            return {"status": "ok", "updated": updated}

        if event != "messages.upsert":
            logger.info("Webhook WhatsApp ignorado: event=%s", payload.get("event"))
            return {"status": "ignored", "reason": "not_a_message_upsert", "event": payload.get("event")}

        saved = 0
        duplicates = 0
        ignored = 0
        status_updates = 0
        for data in items:
            if _from_me(data):
                if await _update_message_status(db, data, payload):
                    status_updates += 1
                else:
                    ignored += 1
                continue

            remote_jid = _remote_jid(data)
            phone = _normalize_webhook_phone(remote_jid)
            body = _extract_message_body(data)
            message_id = _message_id(data)

            if not phone:
                logger.info("Webhook WhatsApp ignorado sem telefone: event=%s message_id=%s", event, message_id)
                ignored += 1
                continue

            if not body:
                logger.info("Webhook WhatsApp ignorado sem corpo suportado: phone=%s message_id=%s", phone, message_id)
                ignored += 1
                continue

            if message_id:
                existing_result = await db.execute(
                    select(WhatsAppMessage).where(WhatsAppMessage.external_message_id == message_id).limit(1)
                )
                if existing_result.scalar_one_or_none():
                    duplicates += 1
                    continue

            customer = await _find_customer_for_phone(db, phone)

            message = WhatsAppMessage(
                customer_id=customer.id if customer else None,
                phone=phone,
                direction="inbound",
                body=body,
                external_message_id=message_id,
                status="received",
                payload=payload,
            )
            db.add(message)
            saved += 1
            logger.info("Nova mensagem WhatsApp: phone=%s customer=%s id=%s", phone, customer.id if customer else None, message_id)

            # Aqui no futuro voce integrara com uma triagem automatica de atendimento.
            # background_tasks.add_task(process_whatsapp_message_with_ai, phone, body)

        await db.flush()
        return {
            "status": "ok",
            "saved": saved,
            "duplicates": duplicates,
            "ignored": ignored,
            "status_updates": status_updates,
        }
    except Exception as e:
        logger.exception("Erro no webhook do WhatsApp: %s", e)
        return {"status": "error", "message": str(e)}
