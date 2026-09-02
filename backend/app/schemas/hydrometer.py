"""Schemas de Hidrômetro."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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
    initial_reading: float = Field(default=0.0, ge=0)
    installation_mode: Literal["field_capture", "dashboard_baseline"] = "field_capture"
    baseline_date: date | None = None

    @model_validator(mode="after")
    def validate_baseline_date(self):
        if self.baseline_date and self.baseline_date > date.today():
            raise ValueError("A data da leitura-base nao pode estar no futuro")
        return self


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
    last_reading_value: float | None = Field(default=None, ge=0)


class HydrometerAdministrativeBaselineRequest(BaseModel):
    value: float = Field(ge=0)
    baseline_date: date

    @model_validator(mode="after")
    def validate_baseline_date(self):
        if self.baseline_date > date.today():
            raise ValueError("A data da leitura-base nao pode estar no futuro")
        return self


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
    frames_base64: list[str] = Field(default_factory=list, max_length=7)
    capture_id: UUID | None = None
    capture_metadata: dict = Field(default_factory=dict)
    frame_metadata: list[dict] = Field(default_factory=list, max_length=8)
    hydrometer_id: UUID | None = None
    stage: str = "reading"
    red_digits: int | None = 3
    black_digits: int | None = None
    previous_value: float | None = None
    hydrometer_brand: str | None = None
    hydrometer_model: str | None = None


class HydrometerResolveCodeRequest(BaseModel):
    code: str


class KimiVisionFeedbackRequest(BaseModel):
    inference_id: UUID | None = None
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
    approve_for_training: bool | None = None
    slot_labels: list[dict] = Field(default_factory=list, max_length=10)


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


class HydrometerReconnectRequest(BaseModel):
    mode: Literal["reading_only", "with_fee"] = "with_fee"
