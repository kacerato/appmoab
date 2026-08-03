"""Schemas de Fatura e Boleto."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.invoice_document import InvoiceDocumentResponse


class InvoiceResponse(BaseModel):
    id: UUID
    customer_id: UUID
    reading_id: UUID | None
    consumption_m3: float
    tariff_rate: float
    amount: float
    original_amount: float | None = None
    custom_adjustment_amount: float = 0.0
    late_fee_amount: float = 0.0
    interest_amount: float = 0.0
    days_overdue_charged: int = 0
    overdue_charges_allowed: bool = True
    overdue_charge_blocked_reason: str | None = None
    adjustment_reason: str | None = None
    charge_type: str = "water"
    reference_month: str
    due_date: date
    payment_provider: str | None = None
    payment_due_date: date | None = None
    efi_charge_id: str | None = None
    efi_status: str | None = None
    efi_barcode: str | None = None
    efi_payment_url: str | None = None
    efi_pdf_url: str | None = None
    efi_pix_qrcode: str | None = None
    efi_payment_receipt_url: str | None = None
    paid_date: date | None
    status: str
    display_status: str | None = None
    display_status_label: str | None = None
    days_until_due: int | None = None
    has_pdf: bool = False
    document_count: int = 0
    documents: list[InvoiceDocumentResponse] = Field(default_factory=list)
    created_at: datetime

    # Dados agregados
    customer_name: str | None = None
    customer_cpf_cnpj: str | None = None
    reading_status: str | None = None
    reading_kind: str | None = None
    can_reverse_reading: bool = False

    model_config = {"from_attributes": True}


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    per_page: int


class InvoiceCreateManual(BaseModel):
    """Criação manual de fatura (para ajustes)."""
    customer_id: UUID
    reading_id: UUID | None = None
    amount: float
    reference_month: str
    due_date: date
    consumption_m3: float = 0.0
    tariff_rate: float = 0.0
    charge_type: str = "manual"


class InvoiceAmountUpdate(BaseModel):
    amount: float
    reason: str | None = None


class InvoiceDueDateUpdate(BaseModel):
    due_date: date


class InvoiceOverdueUpdate(BaseModel):
    days_overdue: int | None = None


class InvoiceStatusUpdate(BaseModel):
    paid_date: date | None = None


class InvoiceReopenRequest(BaseModel):
    reason: str


class InvoiceCancelRequest(BaseModel):
    preserve_reading: bool = True
    reason: str | None = Field(default=None, max_length=500)


class InvoiceSummary(BaseModel):
    """Resumo financeiro para o dashboard."""
    total_pending: float
    total_upcoming: float = 0.0
    total_overdue: float
    total_paid_month: float
    total_invoices: int
    invoices_pending: int
    invoices_upcoming: int = 0
    invoices_overdue: int
    invoices_paid: int


class InvoiceWhatsAppDispatchResponse(BaseModel):
    invoice_id: UUID
    status: str
    reason: str
    detail: str | None = None


class InvoiceEventResponse(BaseModel):
    id: UUID
    invoice_id: UUID
    user_id: UUID | None = None
    event_type: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str | None = None
    payload: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
