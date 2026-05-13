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
from app.services.inter_api import inter_service
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
    effective_days = max(0, days_overdue if days_overdue is not None else (date.today() - invoice.due_date).days)
    invoice.days_overdue_charged = effective_days
    if effective_days <= 0:
        invoice.late_fee_amount = 0.0
        invoice.interest_amount = 0.0
        invoice.amount = round(base_amount + invoice.custom_adjustment_amount, 2)
        return

    invoice.late_fee_amount = round(base_amount * (settings.late_fee_percent / 100), 2)
    invoice.interest_amount = round(base_amount * (settings.daily_interest_percent / 100) * effective_days, 2)
    invoice.amount = round(base_amount + invoice.custom_adjustment_amount + invoice.late_fee_amount + invoice.interest_amount, 2)
    if invoice.status in ("pending", "sent"):
        invoice.status = "overdue"


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

    # Opcional: já emitir o boleto no Inter
    try:
        result = await inter_service.emitir_cobranca(
            valor=invoice.amount,
            cpf_cnpj=customer.cpf_cnpj,
            nome=customer.name,
            email=customer.email or "",
            endereco=customer.address,
            numero=customer.number or "S/N",
            bairro=customer.neighborhood,
            cidade=customer.city,
            uf=customer.state,
            cep=customer.zip_code,
            data_vencimento=invoice.due_date,
            seu_numero=str(invoice.id)[:15],
            mensagem=f"Fatura avulsa {invoice.reference_month}"
        )
        invoice.inter_codigo_solicitacao = result.get("codigoSolicitacao")
        invoice.inter_nosso_numero = result.get("nossoNumero")
        invoice.inter_linha_digitavel = result.get("linhaDigitavel")
        invoice.inter_codigo_barras = result.get("codigoBarras")
        invoice.inter_pix_copia_cola = result.get("pixCopiaECola")
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
    """Emite ou reemite o boleto no Banco Inter para uma fatura existente."""
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.customer)).where(Invoice.id == uuid.UUID(invoice_id))
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")

    if not invoice.customer:
        raise HTTPException(status_code=400, detail="Cliente não associado à fatura")

    try:
        inter_result = await inter_service.emitir_cobranca(
            valor=invoice.amount,
            cpf_cnpj=invoice.customer.cpf_cnpj,
            nome=invoice.customer.name,
            email=invoice.customer.email or "",
            endereco=invoice.customer.address,
            numero=invoice.customer.number or "S/N",
            bairro=invoice.customer.neighborhood,
            cidade=invoice.customer.city,
            uf=invoice.customer.state,
            cep=invoice.customer.zip_code,
            data_vencimento=invoice.due_date,
            seu_numero=str(invoice.id)[:15],
            mensagem=f"Fatura {invoice.reference_month}"
        )
        invoice.inter_codigo_solicitacao = inter_result.get("codigoSolicitacao")
        invoice.inter_nosso_numero = inter_result.get("nossoNumero")
        invoice.inter_linha_digitavel = inter_result.get("linhaDigitavel")
        invoice.inter_codigo_barras = inter_result.get("codigoBarras")
        invoice.inter_pix_copia_cola = inter_result.get("pixCopiaECola")
        await db.flush()
        await db.refresh(invoice)

        # Agenda a busca do PDF e envio por WhatsApp em background
        if invoice.customer.phone and invoice.inter_codigo_solicitacao:
            background_tasks.add_task(
                process_pdf_and_whatsapp,
                invoice.inter_codigo_solicitacao,
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
        logger.error(f"Erro ao emitir boleto forçado: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao emitir boleto: {str(e)}")


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

    if not invoice.inter_codigo_solicitacao:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="boleto_missing",
            detail="A fatura ainda não possui boleto emitido no Banco Inter.",
        )

    if not invoice.pdf_data:
        try:
            invoice.pdf_data = await inter_service.buscar_pdf(invoice.inter_codigo_solicitacao)
            if invoice.pdf_data:
                await db.flush()
        except Exception as exc:
            return InvoiceWhatsAppDispatchResponse(
                invoice_id=invoice.id,
                status="failed",
                reason="pdf_fetch_error",
                detail=f"Não foi possível obter o PDF do boleto: {exc}",
            )

    if not invoice.pdf_data:
        return InvoiceWhatsAppDispatchResponse(
            invoice_id=invoice.id,
            status="failed",
            reason="pdf_missing",
            detail="O Banco Inter ainda não disponibilizou o PDF do boleto.",
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


async def process_pdf_and_whatsapp(codigo_solicitacao: str, phone: str, filename: str, caption: str):
    """Espera o Banco Inter gerar o PDF e depois envia pelo WhatsApp."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Faz tentativas (polling) para buscar o PDF do boleto (geralmente pode demorar alguns segundos)
    pdf_data = None
    for attempt in range(6):
        await asyncio.sleep(5)  # Espera 5 segundos entre as tentativas
        try:
            pdf_data = await inter_service.buscar_pdf(codigo_solicitacao)
            if pdf_data:
                break
        except Exception:
            pass

    if pdf_data:
        logger.info(f"PDF obtido para solicitação {codigo_solicitacao}. Enviando via WhatsApp...")
        await whatsapp_service.send_invoice_document(
            phone=phone,
            pdf_data=pdf_data,
            filename=filename,
            caption=caption
        )
    else:
        logger.warning(f"Não foi possível obter o PDF do boleto {codigo_solicitacao} para envio via WhatsApp.")
