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
from app.models.invoice_event import InvoiceEvent
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.models.whatsapp_message import WhatsAppMessage
from app.models.customer import Customer
from app.models.user import User
from app.schemas.invoice import (
    InvoiceResponse, InvoiceListResponse,
    InvoiceCreateManual, InvoiceSummary, InvoiceWhatsAppDispatchResponse,
    InvoiceEventResponse,
    InvoiceAmountUpdate, InvoiceOverdueUpdate, InvoiceStatusUpdate,
    InvoiceReopenRequest,
)
from app.services.billing_policy import calculate_overdue_amount, payment_due_date_for_provider
from app.services.efi_api import EfiAPIError, efi_service
from app.services.notification_templates import (
    FLOW_NOTIFICATION_TYPES,
    notification_flow_enabled,
    render_invoice_customer_message,
    render_notification_message,
)
from app.services.whatsapp_api import whatsapp_service
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/invoices", tags=["Faturas"])


async def _get_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


def _recalculate_overdue_amount(invoice: Invoice, settings: SystemSetting, days_overdue: int | None = None) -> None:
    base_amount = invoice.original_amount if invoice.original_amount is not None else invoice.amount
    calc = calculate_overdue_amount(
        original_amount=base_amount,
        custom_adjustment_amount=invoice.custom_adjustment_amount,
        due_date=invoice.due_date,
        today=date.today(),
        late_fee_percent=settings.late_fee_percent,
        daily_interest_percent=settings.daily_interest_percent,
        requested_days_overdue=days_overdue,
        overdue_charges_allowed=invoice.overdue_charges_allowed,
    )
    invoice.days_overdue_charged = calc.days_overdue_charged
    invoice.late_fee_amount = calc.late_fee_amount
    invoice.interest_amount = calc.interest_amount
    invoice.amount = calc.total_amount
    if calc.is_overdue and invoice.status in ("pending", "sent"):
        invoice.status = "overdue"


def _apply_efi_result(invoice: Invoice, result: dict, payment_due_date: date | None = None) -> None:
    invoice.payment_provider = "efi"
    invoice.payment_due_date = payment_due_date or invoice.payment_due_date
    invoice.efi_charge_id = result.get("charge_id") or invoice.efi_charge_id
    invoice.efi_status = result.get("status") or invoice.efi_status
    invoice.efi_barcode = result.get("barcode") or invoice.efi_barcode
    invoice.efi_payment_url = result.get("payment_url") or invoice.efi_payment_url
    invoice.efi_pdf_url = result.get("pdf_url") or invoice.efi_pdf_url
    invoice.efi_pix_qrcode = result.get("pix_qrcode") or invoice.efi_pix_qrcode
    invoice.efi_raw_response = result.get("raw") or result


def _merge_efi_raw(invoice: Invoice, **updates) -> dict:
    raw = invoice.efi_raw_response if isinstance(invoice.efi_raw_response, dict) else {}
    return {**raw, **updates}


def _clear_efi_payment_data(invoice: Invoice) -> None:
    invoice.payment_provider = None
    invoice.payment_due_date = None
    invoice.efi_charge_id = None
    invoice.efi_status = None
    invoice.efi_barcode = None
    invoice.efi_payment_url = None
    invoice.efi_pdf_url = None
    invoice.efi_pix_qrcode = None
    invoice.efi_payment_receipt_url = None
    invoice.pdf_data = None


async def _emit_invoice_charge(invoice: Invoice, customer: Customer, settings: SystemSetting, mensagem: str) -> dict:
    payment_due_date = payment_due_date_for_provider(invoice.due_date, date.today())
    result = await efi_service.emitir_cobranca(
        valor=invoice.amount,
        cpf_cnpj=customer.cpf_cnpj,
        nome=customer.name,
        email=customer.email or "",
        telefone=customer.phone,
        endereco=customer.address,
        numero=customer.number or "S/N",
        bairro=customer.neighborhood,
        cidade=customer.city,
        uf=customer.state,
        cep=customer.zip_code,
        data_vencimento=payment_due_date,
        seu_numero=f"AQ-{str(invoice.id)[:8].upper()}",
        mensagem=mensagem,
        multa_percentual=settings.late_fee_percent if invoice.overdue_charges_allowed else 0.0,
        juros_diario_percentual=settings.daily_interest_percent if invoice.overdue_charges_allowed else 0.0,
    )
    _apply_efi_result(invoice, result, payment_due_date)
    if invoice.status == "pending":
        invoice.status = "sent"
    return result


def _append_payment_link(message: str, invoice: Invoice) -> str:
    link = invoice.efi_payment_url
    if not link:
        return message
    if link in message:
        return message
    return f"{message}\n\nLink de pagamento: {link}"


def _invoice_charge_message(invoice: Invoice) -> str:
    if invoice.charge_type == "installation":
        return f"Cobranca de instalacao - Ref: {invoice.reference_month}"
    if invoice.charge_type == "reconnection":
        return f"Cobranca de religacao - Ref: {invoice.reference_month}"
    if invoice.charge_type == "manual":
        return f"Cobranca avulsa - Ref: {invoice.reference_month}"
    return f"Fatura de agua - Ref: {invoice.reference_month}"


def _invoice_customer_message(settings: SystemSetting, invoice: Invoice) -> str:
    customer_name = invoice.customer.name if invoice.customer else "cliente"
    return render_invoice_customer_message(
        settings,
        charge_type=invoice.charge_type,
        customer_name=customer_name,
        amount=invoice.amount,
        due_date=invoice.due_date,
        reference_month=invoice.reference_month,
    )


def _record_outbound_whatsapp(
    db: AsyncSession,
    *,
    invoice: Invoice,
    phone: str,
    body: str,
    status: str,
    message_id: str | None,
    payload: dict,
) -> None:
    db.add(WhatsAppMessage(
        customer_id=invoice.customer_id,
        phone=whatsapp_service.normalize_phone(phone),
        direction="outbound",
        body=body,
        external_message_id=message_id,
        status=status,
        payload=payload,
    ))


def _record_invoice_event(
    db: AsyncSession,
    *,
    invoice: Invoice,
    event_type: str,
    previous_status: str | None = None,
    new_status: str | None = None,
    user: User | None = None,
    reason: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(InvoiceEvent(
        invoice_id=invoice.id,
        user_id=user.id if user else None,
        event_type=event_type,
        previous_status=previous_status,
        new_status=new_status,
        reason=reason.strip() if reason else None,
        payload=payload,
    ))


def _current_month_range() -> tuple[date, date]:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        return month_start, date(today.year + 1, 1, 1)
    return month_start, date(today.year, today.month + 1, 1)


def _invoice_display_status(invoice: Invoice, today: date | None = None) -> tuple[str, str, int | None]:
    today = today or date.today()
    days_until_due = (invoice.due_date - today).days if invoice.due_date else None
    if invoice.status == "pending" and days_until_due is not None and days_until_due > 0:
        return "upcoming", f"A vencer em {days_until_due} dia(s)", days_until_due
    if invoice.status == "pending" and days_until_due == 0:
        return "due_today", "Vence hoje", days_until_due
    labels = {
        "pending": "Pendente",
        "sent": "Enviado",
        "paid": "Pago",
        "overdue": "Vencido",
        "cancelled": "Cancelado",
    }
    return invoice.status, labels.get(invoice.status, invoice.status), days_until_due


def _invoice_response(invoice: Invoice) -> InvoiceResponse:
    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    resp.display_status, resp.display_status_label, resp.days_until_due = _invoice_display_status(invoice)
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


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

    today = date.today()
    if status == "upcoming":
        query = query.where(Invoice.status == "pending", Invoice.due_date > today)
    elif status == "pending":
        query = query.where(Invoice.status == "pending", Invoice.due_date <= today)
    elif status:
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
        items.append(_invoice_response(inv))

    return InvoiceListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/summary", response_model=InvoiceSummary)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resumo financeiro para o dashboard."""
    now = datetime.now(timezone.utc)
    current_month = f"{now.year}-{now.month:02d}"
    month_start, next_month_start = _current_month_range()

    result = await db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= date.today()),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date > date.today()),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.status == "overdue", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(
                case((
                    (Invoice.status == "paid")
                    & (Invoice.paid_date >= month_start)
                    & (Invoice.paid_date < next_month_start),
                    Invoice.amount,
                ), else_=0)
            ), 0),
            func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= date.today()),
                1,
            ), else_=0)),
            func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date > date.today()),
                1,
            ), else_=0)),
            func.sum(case((Invoice.status == "overdue", 1), else_=0)),
            func.sum(case((Invoice.status == "paid", 1), else_=0)),
        )
    )
    row = result.one()

    return InvoiceSummary(
        total_invoices=row[0] or 0,
        total_pending=float(row[1] or 0),
        total_upcoming=float(row[2] or 0),
        total_overdue=float(row[3] or 0),
        total_paid_month=float(row[4] or 0),
        invoices_pending=int(row[5] or 0),
        invoices_upcoming=int(row[6] or 0),
        invoices_overdue=int(row[7] or 0),
        invoices_paid=int(row[8] or 0),
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

    return _invoice_response(invoice)


@router.get("/{invoice_id}/events", response_model=list[InvoiceEventResponse])
async def get_invoice_events(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(InvoiceEvent)
        .where(InvoiceEvent.invoice_id == uuid.UUID(invoice_id))
        .order_by(InvoiceEvent.created_at.desc())
        .limit(100)
    )
    return list(result.scalars().all())


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
        if invoice.efi_pdf_url:
            pdf_data = await efi_service.baixar_pdf(invoice.efi_pdf_url)
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
        original_amount=data.amount,
        reference_month=data.reference_month,
        due_date=data.due_date,
        consumption_m3=data.consumption_m3,
        tariff_rate=data.tariff_rate,
        charge_type=data.charge_type,
        status="pending"
    )
    db.add(invoice)
    await db.flush()
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="invoice_created_manual",
        previous_status=None,
        new_status=invoice.status,
        user=admin,
        reason="Criação manual de fatura",
        payload={"charge_type": invoice.charge_type, "reference_month": invoice.reference_month},
    )

    settings = await _get_system_settings(db)
    # Opcional: ja emitir a cobranca na Efí
    try:
        previous_status = invoice.status
        await _emit_invoice_charge(invoice, customer, settings, _invoice_charge_message(invoice))
        _record_invoice_event(
            db,
            invoice=invoice,
            event_type="efi_charge_emitted",
            previous_status=previous_status,
            new_status=invoice.status,
            user=admin,
            payload={
                "efi_charge_id": invoice.efi_charge_id,
                "efi_status": invoice.efi_status,
                "payment_due_date": invoice.payment_due_date.isoformat() if invoice.payment_due_date else None,
            },
        )
        await db.flush()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Nao foi possivel emitir cobranca Efí automatica: {e}")

    await db.refresh(invoice)
    
    return _invoice_response(invoice)


@router.post("/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura paga não pode ser cancelada.")
    if invoice.status == "cancelled":
        return _invoice_response(invoice)

    cancel_result = None
    if invoice.efi_charge_id and invoice.efi_status not in ("canceled", "cancelled"):
        try:
            cancel_result = await efi_service.cancelar_cobranca(invoice.efi_charge_id)
        except EfiAPIError as exc:
            detail = exc.detail or exc.message
            raise HTTPException(
                status_code=502,
                detail=f"A Efí não confirmou o cancelamento da cobrança: {detail}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Falha ao cancelar cobrança na Efí: {exc}",
            ) from exc

    previous_status = invoice.status
    invoice.status = "cancelled"
    if invoice.efi_charge_id:
        invoice.efi_status = "canceled"
        invoice.efi_raw_response = _merge_efi_raw(
            invoice,
            cancel_result=cancel_result,
            cancelled_at=datetime.now(timezone.utc).isoformat(),
        )
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="invoice_cancelled",
        previous_status=previous_status,
        new_status=invoice.status,
        user=admin,
        payload={
            "efi_charge_id": invoice.efi_charge_id,
            "efi_cancel_result": cancel_result,
        },
    )
    await db.flush()
    await db.refresh(invoice)
    return _invoice_response(invoice)


@router.patch("/{invoice_id}/amount", response_model=InvoiceResponse)
async def update_invoice_amount(
    invoice_id: str,
    data: InvoiceAmountUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura paga nao pode ter valor editado")

    base_amount = invoice.original_amount if invoice.original_amount is not None else invoice.amount
    previous_amount = invoice.amount
    previous_status = invoice.status
    invoice.custom_adjustment_amount = round(data.amount - base_amount, 2)
    invoice.adjustment_reason = data.reason
    invoice.amount = round(data.amount, 2)
    invoice.late_fee_amount = 0.0
    invoice.interest_amount = 0.0
    invoice.days_overdue_charged = 0
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="invoice_amount_adjusted",
        previous_status=previous_status,
        new_status=invoice.status,
        user=admin,
        reason=data.reason,
        payload={"previous_amount": previous_amount, "new_amount": invoice.amount},
    )
    await db.flush()
    await db.refresh(invoice)

    return _invoice_response(invoice)


@router.post("/{invoice_id}/refresh-overdue", response_model=InvoiceResponse)
async def refresh_invoice_overdue_amount(
    invoice_id: str,
    data: InvoiceOverdueUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura ja paga")
    if invoice.due_date >= date.today() and (data.days_overdue or 0) > 0:
        raise HTTPException(status_code=400, detail="Fatura em dia nao pode receber multa ou juros")
    if not invoice.overdue_charges_allowed:
        previous_amount = invoice.amount
        previous_status = invoice.status
        _recalculate_overdue_amount(invoice, await _get_system_settings(db), data.days_overdue)
        _record_invoice_event(
            db,
            invoice=invoice,
            event_type="invoice_overdue_refreshed",
            previous_status=previous_status,
            new_status=invoice.status,
            user=admin,
            reason=invoice.overdue_charge_blocked_reason,
            payload={
                "previous_amount": previous_amount,
                "new_amount": invoice.amount,
                "days_overdue_charged": invoice.days_overdue_charged,
                "late_fee_amount": invoice.late_fee_amount,
                "interest_amount": invoice.interest_amount,
                "overdue_charges_allowed": False,
            },
        )
        await db.flush()
        await db.refresh(invoice)
        return _invoice_response(invoice)

    settings = await _get_system_settings(db)
    previous_amount = invoice.amount
    previous_status = invoice.status
    _recalculate_overdue_amount(invoice, settings, data.days_overdue)
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="invoice_overdue_refreshed",
        previous_status=previous_status,
        new_status=invoice.status,
        user=admin,
        payload={
            "previous_amount": previous_amount,
            "new_amount": invoice.amount,
            "days_overdue_charged": invoice.days_overdue_charged,
            "late_fee_amount": invoice.late_fee_amount,
            "interest_amount": invoice.interest_amount,
        },
    )
    await db.flush()
    await db.refresh(invoice)

    return _invoice_response(invoice)


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceResponse)
async def mark_invoice_paid(
    invoice_id: str,
    data: InvoiceStatusUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    settings = await _get_system_settings(db)
    _recalculate_overdue_amount(invoice, settings)
    previous_status = invoice.status
    invoice.status = "paid"
    invoice.paid_date = data.paid_date or date.today()
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="invoice_marked_paid",
        previous_status=previous_status,
        new_status=invoice.status,
        user=admin,
        payload={"paid_date": invoice.paid_date.isoformat() if invoice.paid_date else None},
    )
    if invoice.customer and invoice.customer.phone and notification_flow_enabled(settings, "payment_confirmed"):
        message = render_notification_message(settings, "payment_confirmed", {
            "nome": invoice.customer.name,
            "valor": f"R$ {invoice.amount:.2f}",
            "data_vencimento": invoice.due_date.strftime("%d/%m/%Y"),
        })
        notification = Notification(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            channel="whatsapp",
            type=FLOW_NOTIFICATION_TYPES["payment_confirmed"],
            status="queued",
            payload={"flow_key": "payment_confirmed", "message": message},
        )
        db.add(notification)
        wa_result = await whatsapp_service.send_text(invoice.customer.phone, message)
        if wa_result:
            notification.status = wa_result.get("status", "failed")
            notification.external_message_id = wa_result.get("message_id")
            notification.sent_at = datetime.now(timezone.utc)
            if wa_result.get("error"):
                notification.error_message = wa_result["error"][:500]
            elif notification.status == "sent":
                _record_outbound_whatsapp(
                    db,
                    invoice=invoice,
                    phone=invoice.customer.phone,
                    body=message,
                    status="sent",
                    message_id=notification.external_message_id,
                    payload={"flow_key": "payment_confirmed", "invoice_id": str(invoice.id)},
                )
        else:
            notification.status = "failed"
            notification.error_message = "WhatsApp desabilitado ou sem canal ativo"
    await db.flush()
    await db.refresh(invoice)
    return _invoice_response(invoice)


@router.post("/{invoice_id}/reopen", response_model=InvoiceResponse)
async def reopen_invoice(
    invoice_id: str,
    data: InvoiceReopenRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    reason = (data.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=400, detail="Informe um motivo claro para reabrir a fatura.")

    previous_status = invoice.status
    previous_charge_id = invoice.efi_charge_id
    invoice.efi_raw_response = _merge_efi_raw(
        invoice,
        reopened_from_charge_id=previous_charge_id,
        reopened_at=datetime.now(timezone.utc).isoformat(),
    )
    _clear_efi_payment_data(invoice)
    invoice.status = "pending"
    invoice.paid_date = None
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="invoice_reopened",
        previous_status=previous_status,
        new_status=invoice.status,
        user=admin,
        reason=reason,
        payload={"previous_efi_charge_id": previous_charge_id},
    )
    await db.flush()
    await db.refresh(invoice)
    return _invoice_response(invoice)


@router.post("/{invoice_id}/cut-notice", response_model=InvoiceWhatsAppDispatchResponse)
async def send_cut_notice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    if not invoice.customer:
        raise HTTPException(status_code=400, detail="Cliente não associado à fatura")

    settings = await _get_system_settings(db)
    days_overdue = max(0, (date.today() - invoice.due_date).days)
    message = (
        f"Aviso de corte: sua fatura {invoice.reference_month} esta atrasada ha {days_overdue} dia(s). "
        f"Regularize o pagamento para evitar desligamento. Valor atualizado: R$ {invoice.amount:.2f}."
    )
    notification = Notification(
        customer_id=invoice.customer_id,
        invoice_id=invoice.id,
        channel="whatsapp",
        type="custom",
        status="queued",
        payload={
            "kind": "cut_notice",
            "cut_notice_days_after_due": settings.cut_notice_days_after_due,
            "message": message,
            "notify_collaborator": True,
        },
    )
    db.add(notification)

    if not whatsapp_service.is_enabled or not invoice.customer.phone:
        notification.status = "failed"
        notification.error_message = "WhatsApp desativado ou cliente sem telefone"
        await db.flush()
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="whatsapp_unavailable",
            detail=notification.error_message,
        )

    wa_result = await whatsapp_service.send_text(invoice.customer.phone, message)
    if not wa_result or wa_result.get("status") != "sent":
        notification.status = "failed"
        notification.error_message = (wa_result or {}).get("error") or "A Evolution API não confirmou o envio."
        await db.flush()
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="dispatch_failed",
            detail=notification.error_message,
        )

    notification.status = "sent"
    notification.sent_at = datetime.now(timezone.utc)
    notification.external_message_id = str(wa_result.get("message_id") or "")
    _record_outbound_whatsapp(
        db,
        invoice=invoice,
        phone=invoice.customer.phone,
        body=message,
        status="sent",
        message_id=notification.external_message_id,
        payload={"flow_key": "cut_notice", "invoice_id": str(invoice.id)},
    )
    await db.flush()
    return InvoiceWhatsAppDispatchResponse(
        invoice_id=invoice.id,
        status="sent",
        reason="ok",
        detail="Aviso de corte enviado ao cliente e registrado para o colaborador.",
    )


@router.post("/{invoice_id}/emit-boleto", response_model=InvoiceResponse)
async def force_emit_boleto(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Emite ou reemite a cobranca Efí para uma fatura existente."""
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if not invoice.customer:
        raise HTTPException(status_code=400, detail="Cliente não associado à fatura")
    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura paga não pode gerar nova cobrança.")
    if invoice.status == "cancelled":
        raise HTTPException(status_code=400, detail="Reabra a fatura antes de emitir uma nova cobrança.")
    if invoice.efi_charge_id or invoice.efi_payment_url:
        raise HTTPException(status_code=400, detail="Esta fatura já possui cobrança Efí emitida.")

    try:
        settings = await _get_system_settings(db)
        previous_status = invoice.status
        await _emit_invoice_charge(invoice, invoice.customer, settings, _invoice_charge_message(invoice))
        _record_invoice_event(
            db,
            invoice=invoice,
            event_type="efi_charge_emitted",
            previous_status=previous_status,
            new_status=invoice.status,
            user=admin,
            payload={
                "efi_charge_id": invoice.efi_charge_id,
                "efi_status": invoice.efi_status,
                "payment_due_date": invoice.payment_due_date.isoformat() if invoice.payment_due_date else None,
            },
        )
        await db.flush()
        await db.refresh(invoice)
        return _invoice_response(invoice)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Erro ao emitir cobranca Efí: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao emitir cobranca Efí: {str(e)}")


@router.post("/{invoice_id}/send-whatsapp", response_model=InvoiceWhatsAppDispatchResponse)
async def send_invoice_whatsapp(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Tenta enviar ou reenviar a fatura manualmente via WhatsApp com diagnóstico claro."""
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if invoice.status == "cancelled":
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="invoice_cancelled",
            detail="Fatura cancelada não pode ser enviada. Reabra e emita uma nova cobrança antes do envio.",
        )

    if not whatsapp_service.is_enabled:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="whatsapp_disabled",
            detail="O envio por WhatsApp está desativado no backend.",
        )

    if not invoice.customer:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="customer_missing",
            detail="A fatura não possui cliente associado.",
        )

    if not invoice.customer.phone:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="phone_missing",
            detail="O cliente não possui telefone cadastrado.",
        )

    normalized_phone = whatsapp_service.normalize_phone(invoice.customer.phone)
    if len(normalized_phone) < 12:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="phone_invalid",
            detail="O telefone do cliente está incompleto ou inválido para WhatsApp.",
        )

    settings = await _get_system_settings(db)
    if not notification_flow_enabled(settings, "invoice_generated"):
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="flow_disabled",
            detail="O fluxo de envio de fatura está desativado nas configurações.",
        )

    base_message = _invoice_customer_message(settings, invoice)

    if not invoice.efi_charge_id and not invoice.efi_payment_url:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="boleto_missing",
            detail="A fatura ainda não possui cobranca emitida na Efí.",
        )

    if not invoice.pdf_data:
        try:
            invoice.pdf_data = await efi_service.baixar_pdf(invoice.efi_pdf_url or "")
            if invoice.pdf_data:
                await db.flush()
        except Exception as exc:
            _record_invoice_event(
                db,
                invoice=invoice,
                event_type="whatsapp_invoice_failed",
                previous_status=invoice.status,
                new_status=invoice.status,
                user=admin,
                reason="Falha ao baixar PDF da cobrança",
                payload={"error": str(exc), "efi_pdf_url": invoice.efi_pdf_url},
            )
            return InvoiceWhatsAppDispatchResponse(
                invoice_id=invoice.id,
                status="failed",
                reason="pdf_fetch_error",
                detail=f"Nao foi possivel obter o PDF da cobranca: {exc}",
            )

    if not invoice.pdf_data:
        if invoice.efi_payment_url:
            text = _append_payment_link(base_message, invoice)
            wa_result = await whatsapp_service.send_text(invoice.customer.phone, text)
            if wa_result and wa_result.get("status") == "sent":
                previous_status = invoice.status
                if invoice.status == "pending":
                    invoice.status = "sent"
                _record_outbound_whatsapp(
                    db,
                    invoice=invoice,
                    phone=invoice.customer.phone,
                    body=text,
                    status="sent",
                    message_id=wa_result.get("message_id"),
                    payload={"flow_key": "invoice_generated", "invoice_id": str(invoice.id), "mode": "payment_link"},
                )
                _record_invoice_event(
                    db,
                    invoice=invoice,
                    event_type="whatsapp_invoice_sent",
                    previous_status=previous_status,
                    new_status=invoice.status,
                    user=admin,
                    payload={"mode": "payment_link", "message_id": wa_result.get("message_id")},
                )
                await db.flush()
                return InvoiceWhatsAppDispatchResponse(
                    invoice_id=invoice.id,
                    status="sent",
                    reason="ok",
                    detail="Link de pagamento enviado pelo WhatsApp.",
                )
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="pdf_missing",
            detail="A Efí ainda não disponibilizou o PDF nem um link de pagamento.",
        )

    wa_result = await whatsapp_service.send_invoice_document(
        phone=invoice.customer.phone,
        pdf_data=invoice.pdf_data,
        filename=f"boleto_{str(invoice.id)[:8]}.pdf",
        caption=_append_payment_link(base_message, invoice),
    )

    if not wa_result or wa_result.get("status") != "sent":
        _record_invoice_event(
            db,
            invoice=invoice,
            event_type="whatsapp_invoice_failed",
            previous_status=invoice.status,
            new_status=invoice.status,
            user=admin,
            reason="A Evolution API não confirmou o envio",
            payload={"error": (wa_result or {}).get("error"), "mode": "document"},
        )
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="dispatch_failed",
            detail=(wa_result or {}).get("error") or "A Evolution API não confirmou o envio.",
        )

    previous_status = invoice.status
    if invoice.status == "pending":
        invoice.status = "sent"
    _record_outbound_whatsapp(
        db,
        invoice=invoice,
        phone=invoice.customer.phone,
        body=_append_payment_link(base_message, invoice),
        status="sent",
        message_id=(wa_result or {}).get("message_id"),
        payload={"flow_key": "invoice_generated", "invoice_id": str(invoice.id), "mode": "document"},
    )
    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="whatsapp_invoice_sent",
        previous_status=previous_status,
        new_status=invoice.status,
        user=admin,
        payload={"mode": "document", "message_id": (wa_result or {}).get("message_id")},
    )
    await db.flush()

    return InvoiceWhatsAppDispatchResponse(
        invoice_id=invoice.id,
        status="sent",
        reason="ok",
        detail=f"Fatura enviada com sucesso para {normalized_phone}.",
    )
