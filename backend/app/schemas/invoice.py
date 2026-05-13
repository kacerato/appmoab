"""Schemas de Fatura e Boleto."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


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
    adjustment_reason: str | None = None
    charge_type: str = "water"
    reference_month: str
    due_date: date
    paid_date: date | None
    status: str
    inter_codigo_solicitacao: str | None
    inter_nosso_numero: str | None
    inter_linha_digitavel: str | None
    inter_codigo_barras: str | None
    inter_pix_copia_cola: str | None
    has_pdf: bool = False
    created_at: datetime

    # Dados agregados
    customer_name: str | None = None
    customer_cpf_cnpj: str | None = None

    model_config = {"from_attributes": True}


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    per_page: int


class InvoiceCreateManual(BaseModel):
    """Criação manual de fatura (para ajustes)."""
    customer_id: UUID
    amount: float
    reference_month: str
    due_date: date
    consumption_m3: float = 0.0
    tariff_rate: float = 0.0
    charge_type: str = "manual"


class InvoiceAmountUpdate(BaseModel):
    amount: float
    reason: str | None = None


class InvoiceOverdueUpdate(BaseModel):
    days_overdue: int | None = None


class InvoiceStatusUpdate(BaseModel):
    paid_date: date | None = None


class InvoiceSummary(BaseModel):
    """Resumo financeiro para o dashboard."""
    total_pending: float
    total_overdue: float
    total_paid_month: float
    total_invoices: int
    invoices_pending: int
    invoices_overdue: int
    invoices_paid: int


class InvoiceWhatsAppDispatchResponse(BaseModel):
    invoice_id: UUID
    status: str
    reason: str
    detail: str | None = None
