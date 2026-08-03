"""Schemas de Tarifa."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class TariffTierBase(BaseModel):
    label: str
    min_m3: float
    max_m3: float
    rate_per_m3: float
    minimum_charge: float = 110.0
    fixed_rate: float = 100.0
    sort_order: int = 0

    @field_validator("max_m3")
    @classmethod
    def validate_range(cls, v: float, info) -> float:
        min_val = info.data.get("min_m3", 0)
        if v <= min_val:
            raise ValueError("max_m3 deve ser maior que min_m3")
        return v

    @field_validator("rate_per_m3")
    @classmethod
    def validate_rate(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Tarifa deve ser positiva")
        return v


class TariffTierCreate(TariffTierBase):
    pass


class TariffTierUpdate(BaseModel):
    label: str | None = None
    min_m3: float | None = None
    max_m3: float | None = None
    rate_per_m3: float | None = None
    minimum_charge: float | None = None
    fixed_rate: float | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class TariffTierResponse(TariffTierBase):
    id: UUID
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TariffListResponse(BaseModel):
    items: list[TariffTierResponse]
    total: int


class MinimumChargeUpdate(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Taxa mínima deve ser positiva")
        return round(value, 2)


class MinimumChargeResponse(BaseModel):
    amount: float
    updated_tiers: int


class BillingCalculation(BaseModel):
    """Resultado do cálculo de faturamento."""
    consumption_m3: float
    tariff_tier_label: str
    tariff_rate: float
    gross_amount: float
    minimum_charge: float
    final_amount: float
    is_minimum_applied: bool
