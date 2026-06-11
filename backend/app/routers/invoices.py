"""
Router de Faturas — Lista, detalhe, PDF e dashboard financeiro.
"""

import uuid
import asyncio
from datetime import date, datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.system_setting import SystemSetting
from app.models.customer import Customer
from app.models.user import User
from app.schemas.invoice import (
    InvoiceResponse, InvoiceListResponse,
    InvoiceCreateManual, InvoiceSummary, InvoiceWhatsAppDispatchResponse,
    InvoiceAmountUpdate, InvoiceOverdueUpdate, InvoiceStatusUpdate,
)
from app.services.billing_policy import calculate_overdue_amount, payment_due_date_for_provider
from app.services.efi_api import efi_service
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
    # Campos legados mantidos preenchidos para telas/relatorios antigos.
    invoice.inter_codigo_solicitacao = invoice.efi_charge_id
    invoice.inter_linha_digitavel = invoice.efi_barcode
    invoice.inter_pix_copia_cola = invoice.efi_pix_qrcode


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
        dias_baixa_apos_vencimento=settings.route_window_days_after_due,
    )
    _apply_efi_result(invoice, result, payment_due_date)
    if invoice.status == "pending":
        invoice.status = "sent"
    return result


def _current_month_range() -> tuple[date, date]:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    if today.month == 12:
        return month_start, date(today.year + 1, 1, 1)
    return month_start, date(today.year, today.month + 1, 1)


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
    month_start, next_month_start = _current_month_range()

    result = await db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(case((Invoice.status == "pending", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.status == "overdue", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(
                case((
                    (Invoice.status == "paid")
                    & (Invoice.paid_date >= month_start)
                    & (Invoice.paid_date < next_month_start),
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

    settings = await _get_system_settings(db)
    # Opcional: ja emitir a cobranca na Efí
    try:
        await _emit_invoice_charge(invoice, customer, settings, f"Fatura avulsa {invoice.reference_month}")
        await db.flush()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Nao foi possivel emitir cobranca Efí automatica: {e}")

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
    invoice.custom_adjustment_amount = round(data.amount - base_amount, 2)
    invoice.adjustment_reason = data.reason
    invoice.amount = round(data.amount, 2)
    invoice.late_fee_amount = 0.0
    invoice.interest_amount = 0.0
    invoice.days_overdue_charged = 0
    await db.flush()
    await db.refresh(invoice)

    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


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
        _recalculate_overdue_amount(invoice, await _get_system_settings(db), data.days_overdue)
        await db.flush()
        await db.refresh(invoice)
        resp = InvoiceResponse.model_validate(invoice)
        resp.has_pdf = invoice.pdf_data is not None
        if invoice.customer:
            resp.customer_name = invoice.customer.name
            resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
        return resp

    settings = await _get_system_settings(db)
    _recalculate_overdue_amount(invoice, settings, data.days_overdue)
    await db.flush()
    await db.refresh(invoice)

    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


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
    invoice.status = "paid"
    invoice.paid_date = data.paid_date or date.today()
    await db.flush()
    await db.refresh(invoice)
    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


@router.post("/{invoice_id}/reopen", response_model=InvoiceResponse)
async def reopen_invoice(
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

    invoice.status = "pending"
    invoice.paid_date = None
    await db.flush()
    await db.refresh(invoice)
    resp = InvoiceResponse.model_validate(invoice)
    resp.has_pdf = invoice.pdf_data is not None
    if invoice.customer:
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
    return resp


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
    background_tasks: BackgroundTasks,
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

    try:
        settings = await _get_system_settings(db)
        efi_result = await _emit_invoice_charge(invoice, invoice.customer, settings, f"Fatura {invoice.reference_month}")
        await db.flush()
        await db.refresh(invoice)

        # Agenda a busca do PDF e envio por WhatsApp em background
        if invoice.customer.phone and invoice.efi_pdf_url:
            background_tasks.add_task(
                process_pdf_and_whatsapp,
                invoice.efi_pdf_url,
                invoice.customer.phone,
                f"boleto_{str(invoice.id)[:8]}.pdf",
                f"Sua fatura do mês {invoice.reference_month} já está disponível."
            )
        
        resp = InvoiceResponse.model_validate(invoice)
        resp.has_pdf = invoice.pdf_data is not None
        resp.customer_name = invoice.customer.name
        resp.customer_cpf_cnpj = invoice.customer.cpf_cnpj
        return resp
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
            return InvoiceWhatsAppDispatchResponse(
                invoice_id=invoice.id,
                status="failed",
                reason="pdf_fetch_error",
                detail=f"Nao foi possivel obter o PDF da cobranca: {exc}",
            )

    if not invoice.pdf_data:
        if invoice.efi_payment_url:
            text = (
                f"Sua fatura do mês {invoice.reference_month} está disponível: {invoice.efi_payment_url}"
            )
            wa_result = await whatsapp_service.send_text(invoice.customer.phone, text)
            if wa_result and wa_result.get("status") == "sent":
                if invoice.status == "pending":
                    invoice.status = "sent"
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
        caption=f"Sua fatura do mês {invoice.reference_month} já está disponível.",
    )

    if not wa_result or wa_result.get("status") != "sent":
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="dispatch_failed",
            detail=(wa_result or {}).get("error") or "A Evolution API não confirmou o envio.",
        )

    if invoice.status == "pending":
        invoice.status = "sent"
        await db.flush()

    return InvoiceWhatsAppDispatchResponse(
        invoice_id=invoice.id,
        status="sent",
        reason="ok",
        detail=f"Fatura enviada com sucesso para {normalized_phone}.",
    )


async def process_pdf_and_whatsapp(pdf_url: str, phone: str, filename: str, caption: str):
    """Baixa o PDF da Efí e depois envia pelo WhatsApp."""
    import logging
    logger = logging.getLogger(__name__)
    
    pdf_data = None
    for attempt in range(6):
        await asyncio.sleep(5)  # Espera 5 segundos entre as tentativas
        try:
            pdf_data = await efi_service.baixar_pdf(pdf_url)
            if pdf_data:
                break
        except Exception:
            pass

    if pdf_data:
        logger.info("PDF Efí obtido. Enviando via WhatsApp...")
        await whatsapp_service.send_invoice_document(
            phone=phone,
            pdf_data=pdf_data,
            filename=filename,
            caption=caption
        )
    else:
        logger.warning("Nao foi possivel obter o PDF Efí para envio via WhatsApp.")
