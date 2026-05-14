"""
Router de Leituras — Upload de foto, OCR, validação e aprovação.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.reading import Reading
from app.models.hydrometer import Hydrometer
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.reading import (
    ReadingCreate, ReadingOCRResult, ReadingConfirm,
    ReadingApprove, ReadingReject, ReadingResponse, ReadingListResponse,
)
from app.services.kimi_vision import kimi_service
from app.services.billing import calculate_billing
from app.services.inter_api import inter_service
from app.utils.security import get_current_user, require_admin
from app.utils.storage import build_public_upload_url, save_photo_from_base64

router = APIRouter(prefix="/readings", tags=["Leituras"])


async def _get_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


@router.get("", response_model=ReadingListResponse)
async def list_readings(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = None,
    hydrometer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista leituras com filtros — usado na fila de aprovação."""
    query = select(Reading).options(
        selectinload(Reading.hydrometer).selectinload(Hydrometer.customer),
        selectinload(Reading.collaborator),
    )

    if status:
        query = query.where(Reading.status == status)
    if hydrometer_id:
        query = query.where(Reading.hydrometer_id == uuid.UUID(hydrometer_id))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * per_page
    query = query.order_by(Reading.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    readings = result.scalars().all()

    items = []
    for r in readings:
        resp = ReadingResponse.model_validate(r)
        resp.collaborator_name = r.collaborator.name if r.collaborator else None
        resp.hydrometer_code = r.hydrometer.code if r.hydrometer else None
        resp.photo_url = build_public_upload_url(r.photo_url)
        if r.hydrometer and r.hydrometer.customer:
            resp.customer_name = r.hydrometer.customer.name
            resp.customer_id = r.hydrometer.customer.id
        items.append(resp)

    return ReadingListResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("", response_model=ReadingOCRResult, status_code=201)
async def create_reading(
    data: ReadingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Upload de foto do hidrômetro pelo app mobile.
    Envia para Kimi K2.6 OCR e retorna dados extraídos.
    """
    # Busca hidrômetro
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.id == data.hydrometer_id)
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrômetro não encontrado")

    # Salva foto
    photo_url = save_photo_from_base64(data.photo_base64, prefix="reading")

    # OCR via Kimi K2.6 fica como veredito interno. Quando o colaborador digitou
    # a leitura, a resposta nao depende mais do OCR para seguir o fluxo.
    ocr_result = {"codigo": None, "leitura_m3": None, "confianca": 0.0}
    if data.current_value is None:
        try:
            ocr_result = await kimi_service.extract_hydrometer_data(data.photo_base64)
        except Exception as e:
            # OCR falhou, mas a leitura ainda pode ser registrada manualmente
            import logging
            logging.getLogger(__name__).warning(f"OCR falhou: {e}")

    current_value = data.current_value
    if current_value is None:
        current_value = ocr_result.get("leitura_m3") or 0.0

    # Cria leitura (status=pending, aguarda confirmação do colaborador)
    reading = Reading(
        hydrometer_id=data.hydrometer_id,
        collaborator_id=user.id,
        current_value=current_value,
        previous_value=hydrometer.last_reading_value,
        consumption=max(0, current_value - hydrometer.last_reading_value),
        photo_url=photo_url,
        photo_extracted_code=data.confirmed_code or ocr_result.get("codigo"),
        photo_extracted_value=ocr_result.get("leitura_m3"),
        ocr_confidence=ocr_result.get("confianca"),
        latitude=data.latitude,
        longitude=data.longitude,
        captured_at=data.captured_at,
        status="pending",
    )
    db.add(reading)
    await db.flush()
    await db.refresh(reading)

    return ReadingOCRResult(
        reading_id=reading.id,
        extracted_code=ocr_result.get("codigo"),
        extracted_value=ocr_result.get("leitura_m3"),
        confidence=ocr_result.get("confianca"),
        matched_customer_name=hydrometer.customer.name if hydrometer.customer else None,
        matched_hydrometer_code=hydrometer.code,
    )


@router.put("/{reading_id}/confirm", response_model=ReadingResponse)
async def confirm_reading(
    reading_id: str,
    data: ReadingConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Colaborador confirma/ajusta os valores após OCR."""
    result = await db.execute(
        select(Reading)
        .options(selectinload(Reading.hydrometer))
        .where(Reading.id == uuid.UUID(reading_id))
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")

    reading.current_value = data.current_value
    reading.consumption = max(0, data.current_value - reading.previous_value)
    if data.confirmed_code:
        reading.photo_extracted_code = data.confirmed_code

    await db.flush()
    await db.refresh(reading)
    return reading


@router.post("/{reading_id}/approve")
async def approve_reading(
    reading_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Gestor aprova leitura → calcula fatura → gera boleto Inter.
    Fluxo completo de aprovação.
    """
    result = await db.execute(
        select(Reading)
        .options(
            selectinload(Reading.hydrometer).selectinload(Hydrometer.customer),
        )
        .where(Reading.id == uuid.UUID(reading_id))
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")
    if reading.status != "pending":
        raise HTTPException(status_code=400, detail=f"Leitura já está '{reading.status}'")

    # Aprova leitura
    reading.status = "approved"
    reading.approved_by = admin.id
    reading.approved_at = datetime.now(timezone.utc)

    # Atualiza última leitura do hidrômetro
    hydrometer = reading.hydrometer
    is_installation_capture = hydrometer.last_reading_date is None
    hydrometer.last_reading_value = reading.current_value
    hydrometer.last_reading_date = datetime.now(timezone.utc)

    customer = hydrometer.customer

    # Determina data de vencimento
    now = datetime.now(timezone.utc)
    due_day = customer.due_day
    if now.day >= due_day:
        # Vencimento no próximo mês
        month = now.month + 1
        year = now.year
        if month > 12:
            month = 1
            year += 1
    else:
        month = now.month
        year = now.year

    from datetime import date
    due_date = date(year, month, due_day)
    ref_month = f"{year}-{month:02d}"

    if is_installation_capture:
        settings = await _get_system_settings(db)
        amount = settings.installation_fee_amount
        consumption_m3 = 0.0
        tariff_rate = 0.0
        charge_type = "installation"
        boleto_message = f"Instalacao do hidrometro {hydrometer.code} - Ref: {ref_month}"
    else:
        billing = await calculate_billing(db, reading.consumption)
        amount = billing.final_amount
        consumption_m3 = billing.consumption_m3
        tariff_rate = billing.tariff_rate
        charge_type = "water"
        boleto_message = f"Consumo: {billing.consumption_m3:.2f}m³ - Ref: {ref_month}"

    # Cria fatura
    invoice = Invoice(
        customer_id=customer.id,
        reading_id=reading.id,
        consumption_m3=consumption_m3,
        tariff_rate=tariff_rate,
        amount=amount,
        original_amount=amount,
        reference_month=ref_month,
        due_date=due_date,
        charge_type=charge_type,
        status="pending",
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)

    # Gera boleto no Inter
    try:
        seu_numero = f"AQ-{str(invoice.id)[:8].upper()}"
        boleto = await inter_service.emitir_cobranca(
            valor=amount,
            cpf_cnpj=customer.cpf_cnpj,
            nome=customer.name,
            email=customer.email or "",
            endereco=customer.address,
            numero=customer.number,
            bairro=customer.neighborhood,
            cidade=customer.city,
            uf=customer.state,
            cep=customer.zip_code,
            data_vencimento=due_date,
            seu_numero=seu_numero,
            mensagem=boleto_message,
        )

        invoice.inter_codigo_solicitacao = boleto.get("codigoSolicitacao")
        invoice.inter_nosso_numero = boleto.get("nossoNumero")
        invoice.inter_linha_digitavel = boleto.get("linhaDigitavel")
        invoice.inter_codigo_barras = boleto.get("codigoBarras")
        invoice.inter_pix_copia_cola = boleto.get("pixCopiaECola")
        invoice.inter_raw_response = boleto.get("raw")
        invoice.status = "sent"

        # Busca PDF
        if boleto.get("codigoSolicitacao"):
            pdf_data = await inter_service.buscar_pdf(boleto["codigoSolicitacao"])
            if pdf_data:
                invoice.pdf_data = pdf_data

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Erro ao gerar boleto: {e}")
        # Fatura criada mas sem boleto — pode ser gerado depois

    await db.flush()

    return {
        "message": "Leitura aprovada e fatura gerada",
        "reading_id": str(reading.id),
        "invoice_id": str(invoice.id),
        "amount": amount,
        "consumption_m3": consumption_m3,
        "tariff_rate": tariff_rate,
        "charge_type": charge_type,
        "boleto_status": invoice.status,
    }


@router.post("/{reading_id}/reject")
async def reject_reading(
    reading_id: str,
    data: ReadingReject,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Gestor rejeita leitura com motivo."""
    result = await db.execute(
        select(Reading).where(Reading.id == uuid.UUID(reading_id))
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")

    reading.status = "rejected"
    reading.rejection_reason = data.reason
    reading.approved_by = admin.id
    reading.approved_at = datetime.now(timezone.utc)
    await db.flush()

    return {"message": "Leitura rejeitada", "reading_id": str(reading.id)}
