"""
Router de Faturas — Lista, detalhe, PDF e dashboard financeiro.
"""

import uuid
import asyncio
from datetime import date, datetime, timezone
from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, case, inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, load_only

from app.database import get_db
from app.models.invoice import Invoice
from app.models.invoice_document import InvoiceDocument
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
from app.schemas.invoice_document import InvoiceDocumentResponse, InvoiceDocumentUpload
from app.services.billing_policy import calculate_overdue_amount, payment_due_date_for_provider
from app.services.efi_api import EfiAPIError, efi_service
from app.services.invoice_documents import (
    BOLETO_PDF,
    DocumentPayload,
    get_or_create_boleto_pdf,
    read_invoice_document,
    store_invoice_document,
    validate_receipt_upload,
)
from app.services.invoice_whatsapp import (
    dispatch_invoice_notification,
    dispatch_invoice_notification_task,
    enqueue_invoice_whatsapp,
)
from app.services.notification_templates import (
    FLOW_NOTIFICATION_TYPES,
    notification_flow_enabled,
    render_invoice_customer_message,
    render_notification_message,
)
from app.services.whatsapp_api import whatsapp_service
from app.utils.security import get_current_user, require_admin
from app.utils.storage import decode_base64_upload, delete_photo

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


def _document_response(document: InvoiceDocument) -> InvoiceDocumentResponse:
    return InvoiceDocumentResponse(
        id=document.id,
        invoice_id=document.invoice_id,
        customer_id=document.customer_id,
        document_type=document.document_type,
        source=document.source,
        original_name=document.original_name,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        provider_document_id=document.provider_document_id,
        metadata=document.metadata_json,
        notes=document.notes,
        created_at=document.created_at,
    )


def _invoice_response(invoice: Invoice) -> InvoiceResponse:
    computed_fields = {
        "display_status",
        "display_status_label",
        "days_until_due",
        "has_pdf",
        "document_count",
        "documents",
        "customer_name",
        "customer_cpf_cnpj",
    }
    # Construa o contrato apenas com colunas escalares. Isso impede que o
    # Pydantic dispare lazy-load assíncrono de relacionamentos em endpoints que
    # não precisam deles (e evita MissingGreenlet em produção).
    payload = {
        field_name: getattr(invoice, field_name)
        for field_name in InvoiceResponse.model_fields
        if field_name not in computed_fields
    }
    resp = InvoiceResponse.model_validate(payload)
    unloaded = inspect(invoice).unloaded
    documents = [] if "documents" in unloaded else list(invoice.documents)
    legacy_pdf_loaded = "pdf_data" not in unloaded and invoice.pdf_data is not None
    resp.has_pdf = bool(
        invoice.efi_pdf_url
        or legacy_pdf_loaded
        or any(document.document_type == BOLETO_PDF for document in documents)
    )
    resp.document_count = len(documents)
    resp.documents = [_document_response(document) for document in documents]
    resp.display_status, resp.display_status_label, resp.days_until_due = _invoice_display_status(invoice)
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


async def _get_or_fetch_boleto_pdf(
    db: AsyncSession,
    invoice: Invoice,
    *,
    source: str,
) -> bytes | None:
    return await get_or_create_boleto_pdf(
        db,
        invoice,
        efi_service.baixar_pdf,
        source=source,
    )


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
    query = select(Invoice).options(
        load_only(
            Invoice.id,
            Invoice.customer_id,
            Invoice.reading_id,
            Invoice.consumption_m3,
            Invoice.tariff_rate,
            Invoice.amount,
            Invoice.original_amount,
            Invoice.custom_adjustment_amount,
            Invoice.late_fee_amount,
            Invoice.interest_amount,
            Invoice.days_overdue_charged,
            Invoice.overdue_charges_allowed,
            Invoice.overdue_charge_blocked_reason,
            Invoice.adjustment_reason,
            Invoice.charge_type,
            Invoice.reference_month,
            Invoice.due_date,
            Invoice.paid_date,
            Invoice.status,
            Invoice.payment_provider,
            Invoice.payment_due_date,
            Invoice.efi_charge_id,
            Invoice.efi_status,
            Invoice.efi_barcode,
            Invoice.efi_payment_url,
            Invoice.efi_pdf_url,
            Invoice.efi_pix_qrcode,
            Invoice.efi_payment_receipt_url,
            Invoice.created_at,
            Invoice.updated_at,
        ),
        selectinload(Invoice.customer),
    )

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
        select(Invoice).options(
            selectinload(Invoice.customer),
            selectinload(Invoice.documents),
        )
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


@router.get("/{invoice_id}/documents", response_model=list[InvoiceDocumentResponse])
async def list_invoice_documents(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    parsed_id = uuid.UUID(invoice_id)
    invoice_exists = await db.scalar(select(func.count()).where(Invoice.id == parsed_id))
    if not invoice_exists:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    result = await db.execute(
        select(InvoiceDocument)
        .where(InvoiceDocument.invoice_id == parsed_id)
        .order_by(InvoiceDocument.created_at.desc())
    )
    return [_document_response(document) for document in result.scalars().all()]


@router.post("/{invoice_id}/documents", response_model=InvoiceDocumentResponse, status_code=201)
async def upload_invoice_document(
    invoice_id: str,
    data: InvoiceDocumentUpload,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Invoice).where(Invoice.id == uuid.UUID(invoice_id)))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    try:
        _, raw, detected_mime = decode_base64_upload(data.file_base64, "bin")
        if detected_mime not in {"application/octet-stream", data.mime_type}:
            raise ValueError("Tipo declarado não corresponde ao arquivo enviado")
        validate_receipt_upload(raw, data.mime_type)
        document = await store_invoice_document(
            db,
            invoice,
            DocumentPayload(
                raw=raw,
                document_type=data.document_type,
                source="admin_upload",
                original_name=data.original_name,
                mime_type=data.mime_type,
                notes=data.notes,
                metadata={"uploaded_by": str(admin.id)},
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _record_invoice_event(
        db,
        invoice=invoice,
        event_type="payment_document_uploaded",
        previous_status=invoice.status,
        new_status=invoice.status,
        user=admin,
        payload={"document_id": str(document.id), "document_type": document.document_type},
    )
    return _document_response(document)


@router.get("/{invoice_id}/documents/{document_id}/download")
async def download_invoice_document(
    invoice_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(InvoiceDocument).where(
            InvoiceDocument.id == uuid.UUID(document_id),
            InvoiceDocument.invoice_id == uuid.UUID(invoice_id),
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    raw = await read_invoice_document(document)
    if raw is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no storage")
    safe_name = document.original_name.replace('"', "").replace("\r", "").replace("\n", "")
    return StreamingResponse(
        BytesIO(raw),
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.delete("/{invoice_id}/documents/{document_id}", status_code=204)
async def delete_invoice_document(
    invoice_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(InvoiceDocument).where(
            InvoiceDocument.id == uuid.UUID(document_id),
            InvoiceDocument.invoice_id == uuid.UUID(invoice_id),
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    if document.document_type in {BOLETO_PDF, "efi_payment_event"}:
        raise HTTPException(status_code=409, detail="Documentos técnicos imutáveis não podem ser excluídos")
    await asyncio.to_thread(delete_photo, document.object_key)
    await db.delete(document)
    await db.flush()


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

    pdf_data = await _get_or_fetch_boleto_pdf(db, invoice, source="invoice_download")
    if not pdf_data:
        raise HTTPException(status_code=404, detail="PDF não disponível")

    return StreamingResponse(
        BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=boleto_{invoice_id[:8]}.pdf"},
    )


@router.post("/manual", response_model=InvoiceResponse, status_code=201)
async def create_manual_invoice(
    data: InvoiceCreateManual,
    background_tasks: BackgroundTasks,
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

    notification = None
    if settings.auto_send_invoice_on_approval:
        notification = await enqueue_invoice_whatsapp(db, invoice, source="manual_invoice_creation")
    if notification:
        background_tasks.add_task(dispatch_invoice_notification_task, str(notification.id))

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
        if invoice.efi_pdf_url:
            try:
                await _get_or_fetch_boleto_pdf(db, invoice, source="manual_emit")
            except Exception as exc:
                _record_invoice_event(
                    db,
                    invoice=invoice,
                    event_type="boleto_document_pending",
                    previous_status=previous_status,
                    new_status=invoice.status,
                    user=admin,
                    reason="Cobrança emitida, mas PDF ainda não foi persistido no R2",
                    payload={"error": str(exc)},
                )
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

    notification = await enqueue_invoice_whatsapp(db, invoice, source="manual_button")
    if not notification:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="flow_disabled",
            detail="O fluxo de envio de fatura esta desativado nas configuracoes.",
        )

    dispatch = await dispatch_invoice_notification(db, notification.id)
    await db.flush()
    return InvoiceWhatsAppDispatchResponse(invoice_id=invoice.id, **dispatch)
