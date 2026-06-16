"""Schemas de Hidrômetro."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HydrometerBase(BaseModel):
    code: str | None = None
    brand: str | None = None
    model: str | None = None
    red_digits: int = 3
    black_digits: int | None = None
    location_description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    allowed_radius_meters: float = 80.0
    location_required: bool = True
    location_source: str | None = None


class HydrometerCreate(HydrometerBase):
    customer_id: UUID
    initial_reading: float = 0.0


class HydrometerUpdate(BaseModel):
    code: str | None = None
    brand: str | None = None
    model: str | None = None
    red_digits: int | None = None
    black_digits: int | None = None
    location_description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    allowed_radius_meters: float | None = None
    location_required: bool | None = None
    is_active: bool | None = None
    last_reading_value: float | None = None


class HydrometerCustomer(BaseModel):
    name: str
    cpf_cnpj: str
    model_config = {"from_attributes": True}

class HydrometerResponse(HydrometerBase):
    id: UUID
    customer_id: UUID
    code: str
    qr_code_token: str
    last_reading_value: float
    last_reading_date: datetime | None
    is_active: bool
    disconnected_at: datetime | None = None
    reconnected_at: datetime | None = None
    disconnection_reason: str | None = None
    installed_at: datetime
    customer: HydrometerCustomer | None = None

    model_config = {"from_attributes": True}


class HydrometerListResponse(BaseModel):
    items: list[HydrometerResponse]
    total: int


class HydrometerIdentifyRequest(BaseModel):
    photo_base64: str


class HydrometerResolveCodeRequest(BaseModel):
    code: str


class KimiVisionFeedbackRequest(BaseModel):
    photo_base64: str | None = None
    predicted_code: str | None = None
    predicted_value: float | None = None
    confirmed_code: str | None = None
    confirmed_value: float | None = None
    hydrometer_id: UUID | None = None
    stage: str = "code"
    confidence: float | None = None
    red_digits: int | None = None
    black_digits: int | None = None
    hydrometer_brand: str | None = None
    hydrometer_model: str | None = None
    reasoning_log: str | None = None
    divergence_reason: str | None = None


class HydrometerIdentifyResponse(BaseModel):
    extracted_code: str | None
    confidence: float | None
    matched: bool
    hydrometer_id: UUID | None = None
    hydrometer_code: str | None = None
    qr_code_token: str | None = None
    customer_id: UUID | None = None
    customer_name: str | None = None
    location_description: str | None = None
    last_reading_value: float | None = None
    last_reading_date: datetime | None = None
    red_digits: int | None = None
    black_digits: int | None = None
    brand: str | None = None
    model: str | None = None


class HydrometerQrResolveRequest(BaseModel):
    qr_code_token: str


class HydrometerDisconnectRequest(BaseModel):
    reason: str | None = None
