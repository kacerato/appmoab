"""Schemas de Hidrômetro."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HydrometerBase(BaseModel):
    code: str
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


class HydrometerResponse(HydrometerBase):
    id: UUID
    customer_id: UUID
    last_reading_value: float
    last_reading_date: datetime | None
    is_active: bool
    installed_at: datetime

    model_config = {"from_attributes": True}


class HydrometerListResponse(BaseModel):
    items: list[HydrometerResponse]
    total: int
