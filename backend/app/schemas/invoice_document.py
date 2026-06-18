from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class InvoiceDocumentResponse(BaseModel):
    id: UUID
    invoice_id: UUID
    customer_id: UUID
    document_type: str
    source: str
    original_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    provider_document_id: str | None = None
    metadata: dict | None = None
    notes: str | None = None
    created_at: datetime


class InvoiceDocumentUpload(BaseModel):
    file_base64: str = Field(min_length=16)
    original_name: str = Field(min_length=1, max_length=255)
    mime_type: str
    document_type: str = "payment_receipt_upload"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
        if normalized not in allowed:
            raise ValueError("Envie um comprovante PDF, JPEG, PNG ou WEBP")
        return normalized

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, value: str) -> str:
        allowed = {"payment_receipt_upload", "payment_confirmation_pdf"}
        if value not in allowed:
            raise ValueError("Tipo de documento de pagamento inválido")
        return value

