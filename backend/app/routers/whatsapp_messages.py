from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import Customer
from app.models.user import User
from app.models.whatsapp_message import WhatsAppMessage
from app.schemas.whatsapp_message import (
    WhatsAppConversationResponse,
    WhatsAppMessageResponse,
    WhatsAppSendMessageRequest,
    WhatsAppSendMessageResponse,
)
from app.services.whatsapp_api import whatsapp_service
from app.utils.security import get_current_user

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


def _phone_suffix(phone: str, size: int = 8) -> str:
    digits = "".join(char for char in phone if char.isdigit())
    return digits[-size:] if len(digits) >= size else digits


def _build_quoted_payload(quoted: WhatsAppMessage | None, sent_text: str) -> dict | None:
    if not quoted:
        return None

    return {
        "quoted_message_id": str(quoted.id),
        "quoted_body": quoted.body[:500],
        "quoted_direction": quoted.direction,
        "quoted_created_at": quoted.created_at.isoformat(),
        "sent_text": sent_text,
    }


def _payload_data(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _extract_stored_message_object(message: WhatsAppMessage) -> dict:
    data = _payload_data(message.payload)
    stored_message = data.get("message")
    if isinstance(stored_message, dict) and stored_message:
        return stored_message
    return {"conversation": message.body}


def _build_evolution_quote(message: WhatsAppMessage) -> dict | None:
    if not message.external_message_id:
        return None

    data = _payload_data(message.payload)
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    remote_jid = key.get("remoteJid") or f"{message.phone}@s.whatsapp.net"
    from_me = key.get("fromMe")
    if from_me is None:
        from_me = message.direction == "outbound"

    return {
        "key": {
            "id": message.external_message_id,
            "remoteJid": remote_jid,
            "fromMe": bool(from_me),
        },
        "message": _extract_stored_message_object(message),
    }


async def _find_customer_by_phone(db: AsyncSession, phone: str) -> Customer | None:
    suffix = _phone_suffix(phone)
    if len(suffix) < 8:
        return None

    result = await db.execute(
        select(Customer)
        .where(
            Customer.phone.is_not(None),
            or_(
                Customer.phone.ilike(f"%{suffix}"),
                Customer.phone.ilike(f"%{suffix[:4]}%{suffix[4:]}"),
            ),
        )
        .order_by(Customer.name)
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/conversations", response_model=list[WhatsAppConversationResponse])
async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    latest = (
        select(
            WhatsAppMessage.phone.label("phone"),
            func.max(WhatsAppMessage.created_at).label("last_at"),
            func.count(WhatsAppMessage.id).label("total_messages"),
        )
        .group_by(WhatsAppMessage.phone)
        .subquery()
    )

    result = await db.execute(
        select(WhatsAppMessage, latest.c.total_messages, Customer.name)
        .join(latest, (WhatsAppMessage.phone == latest.c.phone) & (WhatsAppMessage.created_at == latest.c.last_at))
        .outerjoin(Customer, Customer.id == WhatsAppMessage.customer_id)
        .order_by(desc(WhatsAppMessage.created_at))
        .limit(limit)
    )

    return [
        WhatsAppConversationResponse(
            phone=message.phone,
            customer_id=message.customer_id,
            customer_name=customer_name,
            last_message=message.body,
            last_direction=message.direction,
            last_at=message.created_at,
            total_messages=total_messages,
        )
        for message, total_messages, customer_name in result.all()
    ]


@router.get("/conversations/{phone}/messages", response_model=list[WhatsAppMessageResponse])
async def list_conversation_messages(
    phone: str,
    limit: int = Query(100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.phone == phone)
        .order_by(WhatsAppMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


@router.post("/messages", response_model=WhatsAppSendMessageResponse, status_code=201)
async def send_message(
    data: WhatsAppSendMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    customer: Customer | None = None
    raw_phone = data.phone

    if data.customer_id:
        result = await db.execute(select(Customer).where(Customer.id == data.customer_id))
        customer = result.scalar_one_or_none()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente nao encontrado")
        raw_phone = customer.phone

    if not raw_phone:
        raise HTTPException(status_code=400, detail="Cliente sem telefone cadastrado")

    phone = whatsapp_service.normalize_phone(raw_phone)
    if len(phone) < 12:
        raise HTTPException(status_code=400, detail="Telefone invalido para WhatsApp")

    if not customer:
        customer = await _find_customer_by_phone(db, phone)

    quoted: WhatsAppMessage | None = None
    if data.quoted_message_id:
        quoted_result = await db.execute(
            select(WhatsAppMessage).where(WhatsAppMessage.id == data.quoted_message_id)
        )
        quoted = quoted_result.scalar_one_or_none()
        if not quoted:
            raise HTTPException(status_code=404, detail="Mensagem citada nao encontrada")
        if quoted.phone != phone:
            raise HTTPException(status_code=400, detail="Mensagem citada pertence a outra conversa")

    quoted_payload = _build_evolution_quote(quoted) if quoted else None
    if quoted and not quoted_payload:
        raise HTTPException(
            status_code=400,
            detail="Nao foi possivel responder nativamente essa mensagem porque ela nao tem ID do WhatsApp",
        )

    sent_text = data.text
    if quoted:
        sent_text = data.text

    result = await whatsapp_service.send_text(phone, sent_text, quoted=quoted_payload)
    status = (result or {}).get("status") or "disabled"
    detail = (result or {}).get("error")

    message = WhatsAppMessage(
        customer_id=customer.id if customer else None,
        phone=phone,
        direction="outbound",
        body=data.text,
        external_message_id=(result or {}).get("message_id"),
        status=status,
        payload={
            **(_build_quoted_payload(quoted, sent_text) or {}),
            "quoted": quoted_payload,
            "evolution_response": (result or {}).get("payload"),
        },
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    return WhatsAppSendMessageResponse(
        message=WhatsAppMessageResponse.model_validate(message),
        whatsapp_status=status,
        detail=detail,
    )
