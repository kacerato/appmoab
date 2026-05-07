"""Schemas de Hidrômetro."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HydrometerBase(BaseModel):
    code: str | None = None
    brand: str | None = None
    model: str | None = None
    location_description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class HydrometerCreate(HydrometerBase):
    customer_id: UUID
    initial_reading: float = 0.0


class HydrometerUpdate(BaseModel):
    code: str | None = None
    brand: str | None = None
    model: str | None = None
    location_description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool | None = None


class HydrometerCustomer(BaseModel):
    name: str
    cpf_cnpj: str
    model_config = {"from_attributes": True}

class HydrometerResponse(HydrometerBase):
    id: UUID
    customer_id: UUID
    code: str
    last_reading_value: float
    last_reading_date: datetime | None
    is_active: bool
    installed_at: datetime
    customer: HydrometerCustomer | None = None

    model_config = {"from_attributes": True}


class HydrometerListResponse(BaseModel):
    items: list[HydrometerResponse]
    total: int
