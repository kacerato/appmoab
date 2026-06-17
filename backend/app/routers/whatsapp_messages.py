from copy import deepcopy
from uuid import UUID

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
from app.utils.storage import build_public_upload_url, save_binary_from_base64

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

MEDIA_MESSAGE_TYPES = {
    "stickerMessage": ("sticker", "image/webp"),
    "imageMessage": ("image", "image/jpeg"),
    "videoMessage": ("video", "video/mp4"),
    "audioMessage": ("audio", "audio/ogg"),
    "documentMessage": ("document", "application/octet-stream"),
}


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


def _extract_media_entry_with_key(stored_message: dict) -> tuple[str, str, str, dict] | None:
    for key, (media_type, fallback_mime) in MEDIA_MESSAGE_TYPES.items():
        media = stored_message.get(key)
        if isinstance(media, dict):
            return key, media_type, fallback_mime, media
    return None


def _extract_media_entry(stored_message: dict) -> tuple[str, str, dict] | None:
    media_entry = _extract_media_entry_with_key(stored_message)
    if not media_entry:
        return None
    _, media_type, fallback_mime, media = media_entry
    return media_type, fallback_mime, media


def _looks_like_base64(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("data:"):
        return True
    if len(stripped) < 80:
        return False
    return all(char.isalnum() or char in "+/=\r\n" for char in stripped)


def _find_media_base64(value: object) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if _looks_like_base64(stripped) else ""

    if isinstance(value, list):
        for item in value:
            found = _find_media_base64(item)
            if found:
                return found
        return ""

    if not isinstance(value, dict):
        return ""

    for key in ("base64", "media", "file", "data"):
        item = value.get(key)
        if isinstance(item, str) and _looks_like_base64(item):
            return item.strip()

    for item in value.values():
        found = _find_media_base64(item)
        if found:
            return found

    return ""


def _media_data_uri(base64_value: str, mime_type: str) -> str:
    if base64_value.startswith("data:"):
        return base64_value
    return f"data:{mime_type};base64,{base64_value}"


def _media_message_key(mime_type: str | None) -> tuple[str, str]:
    normalized = (mime_type or "").lower()
    if normalized.startswith("image/"):
        return "image", "imageMessage"
    if normalized.startswith("video/"):
        return "video", "videoMessage"
    if normalized.startswith("audio/"):
        return "audio", "audioMessage"
    return "document", "documentMessage"


def _persist_fetched_media(
    message: WhatsAppMessage,
    *,
    media_key: str,
    media_type: str,
    mime_type: str,
    file_name: str | None,
    data_uri: str,
) -> str:
    stored_file_path = save_binary_from_base64(data_uri, prefix="whatsapp", fallback_ext="bin")
    public_file_url = build_public_upload_url(stored_file_path)

    payload = deepcopy(message.payload) if isinstance(message.payload, dict) else {}
    container = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    stored_message = container.get("message") if isinstance(container.get("message"), dict) else {}
    media = stored_message.get(media_key) if isinstance(stored_message.get(media_key), dict) else {}
    media.update({
        "fileName": file_name,
        "mimetype": mime_type,
        "url": public_file_url,
        "storedFilePath": stored_file_path,
    })
    stored_message[media_key] = media
    container["message"] = stored_message
    payload["media"] = {
        "type": media_type,
        "file_name": file_name,
        "mime_type": mime_type,
        "stored_file_path": stored_file_path,
        "public_file_url": public_file_url,
    }
    message.payload = payload
    return public_file_url


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


@router.get("/messages/{message_id}/media")
async def get_message_media(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.id == message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Mensagem nao encontrada")

    stored_message = _extract_stored_message_object(message)
    media_entry = _extract_media_entry_with_key(stored_message)
    if not media_entry:
        raise HTTPException(status_code=400, detail="Mensagem sem midia suportada")

    media_key, media_type, fallback_mime, media = media_entry
    mime_type = str(media.get("mimetype") or media.get("mimeType") or fallback_mime)
    file_name = media.get("fileName") or media.get("filename") or media.get("title")
    direct_base64 = _find_media_base64({"message": stored_message, "payload": message.payload})
    if direct_base64:
        return {
            "message_id": str(message.id),
            "media_type": media_type,
            "mime_type": mime_type,
            "file_name": file_name,
            "data_uri": _media_data_uri(direct_base64, mime_type),
        }

    evolution_message = _build_evolution_quote(message)
    if not evolution_message:
        raise HTTPException(status_code=400, detail="Mensagem sem ID externo para buscar midia")

    result_payload = await whatsapp_service.get_media_base64(
        evolution_message,
        convert_to_mp4=media_type == "video",
    )
    if not result_payload or result_payload.get("status") != "ok":
        raise HTTPException(
            status_code=502,
            detail=(result_payload or {}).get("error") or "Nao foi possivel buscar a midia na Evolution API",
        )

    payload = result_payload.get("payload")
    fetched_base64 = _find_media_base64(payload)
    if not fetched_base64:
        raise HTTPException(status_code=502, detail="Evolution API nao retornou a midia em base64")

    data_uri = _media_data_uri(fetched_base64, mime_type)
    public_file_url = _persist_fetched_media(
        message,
        media_key=media_key,
        media_type=media_type,
        mime_type=mime_type,
        file_name=str(file_name) if file_name else None,
        data_uri=data_uri,
    )
    await db.flush()

    return {
        "message_id": str(message.id),
        "media_type": media_type,
        "mime_type": mime_type,
        "file_name": file_name,
        "data_uri": data_uri,
        "url": public_file_url,
    }


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

    sent_text = data.text.strip()
    stored_file_path: str | None = None
    public_file_url: str | None = None
    media_payload: dict | None = None

    if data.file_base64:
        mediatype, message_key = _media_message_key(data.mime_type)
        stored_file_path = save_binary_from_base64(data.file_base64, prefix="whatsapp", fallback_ext="bin")
        public_file_url = build_public_upload_url(stored_file_path)
        result = await whatsapp_service.send_media(
            phone=phone,
            media_base64=data.file_base64,
            filename=data.file_name or "arquivo",
            caption=sent_text,
            mediatype=mediatype,
            mimetype=data.mime_type,
            quoted=quoted_payload,
        )
        media_payload = {
            message_key: {
                "fileName": data.file_name,
                "mimetype": data.mime_type,
                "url": public_file_url,
            }
        }
    else:
        result = await whatsapp_service.send_text(phone, sent_text, quoted=quoted_payload)

    status = (result or {}).get("status") or "disabled"
    detail = (result or {}).get("error")
    body = sent_text or f"Arquivo enviado: {data.file_name}"

    message = WhatsAppMessage(
        customer_id=customer.id if customer else None,
        phone=phone,
        direction="outbound",
        body=body,
        external_message_id=(result or {}).get("message_id"),
        status=status,
        payload={
            **(_build_quoted_payload(quoted, sent_text) or {}),
            "quoted": quoted_payload,
            "evolution_response": (result or {}).get("payload"),
            "message": media_payload,
            "media": {
                "file_name": data.file_name,
                "mime_type": data.mime_type,
                "stored_file_path": stored_file_path,
                "public_file_url": public_file_url,
            } if media_payload else None,
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
