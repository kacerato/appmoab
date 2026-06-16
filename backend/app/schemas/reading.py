"""Schemas de Leitura — Upload de foto + dados OCR + aprovação."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReadingCreate(BaseModel):
    """Enviado pelo app mobile ao capturar foto."""
    hydrometer_id: UUID
    photo_base64: str
    current_value: float | None = None
    confirmed_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_accuracy_meters: float | None = None
    captured_at: datetime
    anomaly_override_reason: str | None = None


class ReadingOCRResult(BaseModel):
    """Resultado do OCR retornado ao colaborador para validação."""
    reading_id: UUID
    extracted_code: str | None
    extracted_value: float | None
    confidence: float | None
    matched_customer_name: str | None
    matched_hydrometer_code: str | None


class ReadingConfirm(BaseModel):
    """Colaborador confirma ou ajusta os valores extraídos."""
    current_value: float
    confirmed_code: str | None = None


class ReadingApprove(BaseModel):
    """Gestor aprova a leitura no painel."""
    pass


class ReadingReject(BaseModel):
    """Gestor rejeita a leitura com motivo."""
    reason: str


class ReadingResponse(BaseModel):
    id: UUID
    hydrometer_id: UUID
    collaborator_id: UUID
    current_value: float
    previous_value: float
    consumption: float
    photo_url: str
    photo_extracted_code: str | None
    photo_extracted_value: float | None
    ocr_confidence: float | None
    latitude: float | None
    longitude: float | None
    location_accuracy_meters: float | None = None
    distance_from_hydrometer_meters: float | None = None
    location_status: str = "unchecked"
    captured_at: datetime
    validation_flags: list[dict] = Field(default_factory=list)
    anomaly_override_reason: str | None = None
    status: str
    rejection_reason: str | None
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime

    # Dados agregados (preenchidos no router)
    collaborator_name: str | None = None
    hydrometer_code: str | None = None
    customer_name: str | None = None
    customer_id: UUID | None = None

    model_config = {"from_attributes": True}


class ReadingListResponse(BaseModel):
    items: list[ReadingResponse]
    total: int
    page: int
    per_page: int
