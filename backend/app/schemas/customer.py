"""Schemas de Cliente — Validação completa com CPF/CNPJ."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


class CustomerBase(BaseModel):
    name: str
    cpf_cnpj: str
    phone: str | None = None
    email: EmailStr | None = None
    address: str
    number: str = "S/N"
    complement: str | None = None
    neighborhood: str
    city: str
    state: str
    zip_code: str
    due_day: int = 10
    has_hydrometer: bool = True
    notes: str | None = None

    @field_validator("due_day")
    @classmethod
    def validate_due_day(cls, v: int) -> int:
        if not 1 <= v <= 28:
            raise ValueError("Dia de vencimento deve ser entre 1 e 28")
        return v

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        v = v.upper().strip()
        valid_states = {
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        }
        if v not in valid_states:
            raise ValueError(f"UF inválida: {v}")
        return v

    @field_validator("cpf_cnpj")
    @classmethod
    def validate_cpf_cnpj(cls, v: str) -> str:
        # Remove formatação, mantém apenas dígitos
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) not in (11, 14):
            raise ValueError("CPF deve ter 11 dígitos ou CNPJ 14 dígitos")
        return digits


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    due_day: int | None = None
    has_hydrometer: bool | None = None
    status: str | None = None
    notes: str | None = None

    @field_validator("due_day")
    @classmethod
    def validate_due_day(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 28:
            raise ValueError("Dia de vencimento deve ser entre 1 e 28")
        return v


class CustomerResponse(CustomerBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerDetailResponse(CustomerResponse):
    """Response completo incluindo hidrômetros e resumo de faturas."""
    hydrometers: list["HydrometerResponse"] = []
    total_invoices: int = 0
    total_pending: float = 0.0
    total_overdue: float = 0.0
    last_reading_date: datetime | None = None


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int
    page: int
    per_page: int


# Import circular guard
from app.schemas.hydrometer import HydrometerResponse  # noqa: E402

CustomerDetailResponse.model_rebuild()
