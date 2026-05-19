from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WhatsAppConversationResponse(BaseModel):
    phone: str
    customer_id: UUID | None = None
    customer_name: str | None = None
    last_message: str
    last_direction: str
    last_at: datetime
    total_messages: int


class WhatsAppMessageResponse(BaseModel):
    id: UUID
    customer_id: UUID | None = None
    phone: str
    direction: str
    body: str
    status: str
    external_message_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
