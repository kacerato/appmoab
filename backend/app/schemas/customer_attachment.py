from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class CustomerAttachmentCreate(BaseModel):
    original_name: str
    file_base64: str
    mime_type: str
    reference_month: str | None = None
    notes: str | None = None

    @field_validator("reference_month")
    @classmethod
    def validate_reference_month(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if len(value) != 7 or value[4] != "-":
            raise ValueError("A referência deve seguir o formato YYYY-MM")
        return value


class CustomerAttachmentResponse(BaseModel):
    id: UUID
    customer_id: UUID
    kind: str
    original_name: str
    mime_type: str
    reference_month: str | None = None
    notes: str | None = None
    download_url: str
    created_at: datetime

    model_config = {"from_attributes": True}
