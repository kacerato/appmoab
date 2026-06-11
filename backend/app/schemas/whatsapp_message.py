from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


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
    payload: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppSendMessageRequest(BaseModel):
    customer_id: UUID | None = None
    phone: str | None = None
    text: str
    quoted_message_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Informe a mensagem")
        if len(value) > 4000:
            raise ValueError("Mensagem muito longa")
        return value

    @field_validator("phone", mode="before")
    @classmethod
    def empty_phone_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_destination(self) -> "WhatsAppSendMessageRequest":
        if not self.customer_id and not self.phone:
            raise ValueError("Informe um cliente ou telefone")
        return self


class WhatsAppSendMessageResponse(BaseModel):
    message: WhatsAppMessageResponse
    whatsapp_status: str
    detail: str | None = None
