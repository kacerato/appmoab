"""Schemas de Dedução."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DeductionCreate(BaseModel):
    label: str
    amount: float
    sort_order: int = 0


class DeductionUpdate(BaseModel):
    label: str | None = None
    amount: float | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class DeductionResponse(BaseModel):
    id: UUID
    label: str
    amount: float
    is_active: bool
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DeductionListResponse(BaseModel):
    items: list[DeductionResponse]
    total: float
