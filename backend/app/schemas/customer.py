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

    @field_validator("phone", "email", "complement", "notes", mode="before")
    @classmethod
    def empty_optional_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("due_day")
    @classmethod
    def validate_due_day(cls, value: int) -> int:
        if not 1 <= value <= 28:
            raise ValueError("Dia de vencimento deve ser entre 1 e 28")
        return value

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: str) -> str:
        value = value.upper().strip()
        valid_states = {
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        }
        if value not in valid_states:
            raise ValueError(f"UF invalida: {value}")
        return value

    @field_validator("cpf_cnpj")
    @classmethod
    def validate_cpf_cnpj(cls, value: str) -> str:
        digits = "".join(char for char in value if char.isdigit())
        if len(digits) not in (11, 14):
            raise ValueError("CPF deve ter 11 digitos ou CNPJ 14 digitos")
        return digits


class CustomerCreate(CustomerBase):
    hydrometer_initial_reading: float = 0.0
    hydrometer_red_digits: int = 3
    hydrometer_black_digits: int | None = None
    hydrometer_brand: str | None = None
    hydrometer_model: str | None = None
    hydrometer_location_description: str | None = None


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

    @field_validator("phone", "email", "complement", "notes", mode="before")
    @classmethod
    def empty_optional_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("due_day")
    @classmethod
    def validate_due_day(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 28:
            raise ValueError("Dia de vencimento deve ser entre 1 e 28")
        return value


class CustomerResponse(CustomerBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: datetime
    hydrometers: list["HydrometerResponse"] = []
    billing_status: str = "normal"
    billing_status_label: str = "Em dia"
    days_until_due: int | None = None
    last_paid_date: datetime | None = None
    next_invoice_reference_month: str | None = None
    next_invoice_due_date: datetime | None = None

    model_config = {"from_attributes": True}


class CustomerDetailResponse(CustomerResponse):
    hydrometers: list["HydrometerResponse"] = []
    attachments: list["CustomerAttachmentResponse"] = []
    total_invoices: int = 0
    total_pending: float = 0.0
    total_overdue: float = 0.0
    last_reading_date: datetime | None = None


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int
    page: int
    per_page: int


from app.schemas.customer_attachment import CustomerAttachmentResponse  # noqa: E402
from app.schemas.hydrometer import HydrometerResponse  # noqa: E402

CustomerDetailResponse.model_rebuild()
