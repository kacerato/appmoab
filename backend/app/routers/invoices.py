"""
Router de Faturas — Lista, detalhe, PDF e dashboard financeiro.
"""

import uuid
from datetime import date, datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.invoice import Invoice
from app.models.customer import Customer
from app.models.user import User
from app.schemas.invoice import (
    InvoiceResponse, InvoiceListResponse,
    InvoiceCreateManual, InvoiceSummary,
)
from app.services.inter_api import inter_service
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/invoices", tags=["Faturas"])


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = None,
    customer_id: str | None = None,
    reference_month: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Invoice).options(selectinload(Invoice.customer))

    if status:
        query = query.where(Invoice.status == status)
    if customer_id:
        query = query.where(Invoice.customer_id == uuid.UUID(customer_id))
    if reference_month:
        query = query.where(Invoice.reference_month == reference_month)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * per_page
    query = query.order_by(Invoice.due_date.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    invoices = result.scalars().all()

    items = []
    for inv in invoices:
        resp = InvoiceResponse.model_validate(inv)
        resp.has_pdf = inv.pdf_data is not None
        if inv.customer:
            resp.customer_name = inv.customer.name
            resp.customer_cpf_cnpj = inv.customer.cpf_cnpj
        items.append(resp)

    return InvoiceListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/summary", response_model=InvoiceSummary)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resumo financeiro para o dashboard."""
    now = datetime.now(timezone.utc)
    current_month = f"{now.year}-{now.month:02d}"

    result = await db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(case((Invoice.status == "pending", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.status == "overdue", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(
                case((
                    (Invoice.status == "paid") & (Invoice.reference_month == current_month),
                    Invoice.amount,
                ), else_=0)
            ), 0),
            func.sum(case((Invoice.status == "pending", 1), else_=0)),
            func.sum(case((Invoice.status == "overdue", 1), else_=0)),
            func.sum(case((Invoice.status == "paid", 1), else_=0)),
        )
    )
    row = result.one()

    return InvoiceSummary(
        total_invoices=row[0] or 0,
        total_pending=float(row[1] or 0),
        total_overdue=float(row[2] or 0),
        total_paid_month=float(row[3] or 0),
        invoices_pending=int(row[4] or 0),
        invoices_overdue=int(row[5] or 0),
        invoices_paid=int(row[6] or 0),
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer))
        .where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


@router.get("/{invoice_id}/pdf")
async def download_pdf(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download do PDF do boleto."""
    result = await db.execute(
        select(Invoice).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if not invoice.pdf_data:
        # Tenta buscar do Inter se tiver código
        if invoice.inter_codigo_solicitacao:
            pdf_data = await inter_service.buscar_pdf(invoice.inter_codigo_solicitacao)
            if pdf_data:
                invoice.pdf_data = pdf_data
                await db.flush()
            else:
                raise HTTPException(status_code=404, detail="PDF não disponível")
        else:
            raise HTTPException(status_code=404, detail="PDF não disponível")

    return StreamingResponse(
        BytesIO(invoice.pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=boleto_{invoice_id[:8]}.pdf"},
    )


@router.post("/manual", response_model=InvoiceResponse, status_code=201)
async def create_manual_invoice(
    data: InvoiceCreateManual,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Gera uma fatura/boleto avulso manualmente."""
    customer_result = await db.execute(select(Customer).where(Customer.id == data.customer_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    invoice = Invoice(
        customer_id=data.customer_id,
        amount=data.amount,
        reference_month=data.reference_month,
        due_date=data.due_date,
        consumption_m3=data.consumption_m3,
        tariff_rate=data.tariff_rate,
        status="pending"
    )
    db.add(invoice)
    await db.flush()

    # Opcional: já emitir o boleto no Inter
    try:
        from app.services.billing_engine import BillingEngine
        engine = BillingEngine(db)
        await engine._emit_inter_boleto(invoice, customer)
        await db.flush()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Não foi possível emitir boleto Inter automático: {e}")

    await db.refresh(invoice)
    
    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    resp.customer_name = customer.name
    resp.customer_cpf_cnpj = customer.cpf_cnpj
    return resp


@router.post("/{invoice_id}/cancel", status_code=200)
async def cancel_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    invoice.status = "cancelled"
    await db.flush()
    return {"message": "Fatura cancelada", "invoice_id": str(invoice.id)}
