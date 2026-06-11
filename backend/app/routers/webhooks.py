"""
AquaMoab — Webhooks Router.
Recebe requisições de serviços externos, como o nosso microserviço de WhatsApp.
"""

from datetime import datetime

from fastapi import APIRouter, Request, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.whatsapp_message import WhatsAppMessage
from app.services.efi_api import efi_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


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

    invoice.efi_status = current_status
    invoice.efi_raw_response = detail
    mapped_status = _map_efi_status(current_status, invoice)
    invoice.status = mapped_status
    if mapped_status == "paid":
        received_at = latest.get("received_by_bank_at") or latest.get("created_at")
        try:
            invoice.paid_date = datetime.fromisoformat(str(received_at)[:10]).date()
        except ValueError:
            from datetime import date
            invoice.paid_date = date.today()

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
    try:
        payload = await request.json()
        
        # O Evolution API envia vários eventos. Só queremos mensagens recebidas.
        event = payload.get("event")
        if event != "messages.upsert":
            return {"status": "ignored", "reason": "not a message upsert"}
            
        data = payload.get("data", {})
        key = data.get("key", {})
        
        if key.get("fromMe"):
            return {"status": "ignored", "reason": "message sent by me"}
            
        remote_jid = key.get("remoteJid", "")
        phone = remote_jid.split("@")[0]
        
        message_obj = data.get("message", {})
        
        # Pega texto simples ou estendido
        body = ""
        if "conversation" in message_obj:
            body = message_obj["conversation"]
        elif "extendedTextMessage" in message_obj:
            body = message_obj["extendedTextMessage"].get("text", "")
            
        if not body:
            return {"status": "ignored", "reason": "empty or unsupported message type"}
        
        logger.info(f"Nova mensagem (Evolution API) de {phone}: {body}")

        digits = "".join(char for char in phone if char.isdigit())
        customer = None
        if len(digits) >= 8:
            customer_result = await db.execute(
                select(Customer).where(Customer.phone.ilike(f"%{digits[-8:]}%")).limit(1)
            )
            customer = customer_result.scalar_one_or_none()
        message_id = key.get("id") or data.get("messageId")

        message = WhatsAppMessage(
            customer_id=customer.id if customer else None,
            phone=digits or phone,
            direction="inbound",
            body=body,
            external_message_id=message_id,
            status="received",
            payload=payload,
        )
        db.add(message)
        await db.flush()
        
        # Aqui no futuro você integrará com o Kimi (Moonshot AI)
        # background_tasks.add_task(process_whatsapp_message_with_ai, phone, body)
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro no webhook do WhatsApp: {e}")
        return {"status": "error", "message": str(e)}
