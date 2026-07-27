"""Schemas de Leitura — Upload de foto + dados OCR + aprovação."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReadingCreate(BaseModel):
    """Enviado pelo app mobile ao capturar foto."""
    hydrometer_id: UUID
    photo_base64: str
    # Compatibilidade temporaria com APKs antigos. O valor recebido aqui e
    # apenas uma sugestao legada e nunca e consolidado como leitura oficial.
    current_value: float | None = None
    confirmed_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_accuracy_meters: float | None = None
    captured_at: datetime
    anomaly_override_reason: str | None = None
    vision_inference_id: UUID | None = None
    cycle_id: UUID | None = None


class ReadingOCRResult(BaseModel):
    """Recibo da captura e da sugestao OCR enviada para o dashboard."""
    reading_id: UUID
    extracted_code: str | None
    extracted_value: float | None
    confidence: float | None
    matched_customer_name: str | None
    matched_hydrometer_code: str | None


class ReadingConfirm(BaseModel):
    """Contrato legado, agora restrito a gestores."""
    current_value: float
    confirmed_code: str | None = None


class ReadingApprove(BaseModel):
    """Gestor confirma ou ajusta a sugestao visual no painel."""
    current_value: float | None = Field(default=None, ge=0)
    confirmed_code: str | None = None
    adjustment_reason: str | None = Field(default=None, max_length=500)


class ReadingReject(BaseModel):
    """Gestor rejeita a leitura com motivo."""
    reason: str


class ReadingResponse(BaseModel):
    id: UUID
    hydrometer_id: UUID
    collaborator_id: UUID
    current_value: float | None
    previous_value: float
    consumption: float | None
    photo_url: str
    photo_extracted_code: str | None
    photo_extracted_value: float | None
    ocr_confidence: float | None
    vision_inference_id: UUID | None = None
    cycle_id: UUID | None = None
    reference_month: str | None = None
    reading_kind: str = "water"
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
    review_adjustment_reason: str | None = None
    created_at: datetime

    # Dados agregados (preenchidos no router)
    collaborator_name: str | None = None
    hydrometer_code: str | None = None
    customer_name: str | None = None
    customer_id: UUID | None = None
    is_installation: bool = False
    charge_type: str | None = None
    vision_predicted_code: str | None = None
    vision_predicted_value: float | None = None
    vision_confidence: float | None = None
    vision_decision: str | None = None
    vision_digits: list[dict] = Field(default_factory=list)
    vision_alternatives: list = Field(default_factory=list)
    vision_quality: dict = Field(default_factory=dict)
    vision_flags: list = Field(default_factory=list)
    vision_rectified_url: str | None = None
    vision_original_url: str | None = None
    vision_frame_urls: list[str] = Field(default_factory=list)
    vision_selected_frame_index: int | None = None

    model_config = {"from_attributes": True}


class ReadingListResponse(BaseModel):
    items: list[ReadingResponse]
    total: int
    page: int
    per_page: int
