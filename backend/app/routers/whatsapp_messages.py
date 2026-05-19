from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import Customer
from app.models.user import User
from app.models.whatsapp_message import WhatsAppMessage
from app.schemas.whatsapp_message import WhatsAppConversationResponse, WhatsAppMessageResponse
from app.utils.security import get_current_user

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


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
