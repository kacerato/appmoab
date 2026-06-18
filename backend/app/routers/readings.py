"""
Router de Leituras — Upload de foto, OCR, validação e aprovação.
"""

import asyncio
import logging
import math
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_factory, get_db
from app.models.notification import Notification
from app.models.reading import Reading
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.invoice_event import InvoiceEvent
from app.models.system_setting import SystemSetting
from app.models.whatsapp_message import WhatsAppMessage
from app.models.user import User
from app.models.vision_inference import VisionInference
from app.schemas.reading import (
    ReadingCreate, ReadingOCRResult, ReadingConfirm,
    ReadingReject, ReadingResponse, ReadingListResponse,
)
from app.services.glm_ocr import glm_ocr_service
from app.services.billing import calculate_billing
from app.services.billing_policy import (
    payment_due_date_for_provider,
    resolve_invoice_due_date,
    should_block_overdue_charges_for_late_reading,
)
from app.services.efi_api import efi_service
from app.services.invoice_documents import get_or_create_boleto_pdf
from app.services.notification_templates import (
    FLOW_NOTIFICATION_TYPES,
    notification_flow_enabled,
    render_invoice_customer_message,
)
from app.services.whatsapp_api import whatsapp_service
from app.utils.security import get_current_user, require_admin
from app.utils.storage import build_public_upload_url, save_photo_from_base64

router = APIRouter(prefix="/readings", tags=["Leituras"])
logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_RADIUS_METERS = 80.0
CRITICAL_DISTANCE_MULTIPLIER = 4
LOW_ACCURACY_THRESHOLD_METERS = 50.0
ROLLOVER_PREVIOUS_THRESHOLD = 0.90
BILLING_CYCLE_CHARGE_TYPES = ("water", "installation")
ACTIVE_INVOICE_STATUSES = ("pending", "sent", "paid", "overdue")
ACTIVE_READING_STATUSES = ("pending", "approved")


def _flag(code: str, label: str, message: str, severity: str = "warning") -> dict:
    return {"code": code, "label": label, "message": message, "severity": severity}


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _rollover_limit(hydrometer: Hydrometer) -> float:
    black_digits = hydrometer.black_digits or 4
    return float(10 ** black_digits)


def _evaluate_reading(
    *,
    hydrometer: Hydrometer,
    current_value: float,
    previous_value: float,
    latitude: float | None,
    longitude: float | None,
    location_accuracy_meters: float | None,
    anomaly_override_reason: str | None = None,
) -> tuple[float, str, float | None, list[dict]]:
    flags: list[dict] = []
    distance: float | None = None
    location_status = "ok"

    if latitude is None or longitude is None:
        location_status = "missing_capture" if hydrometer.location_required else "unchecked"
        if hydrometer.location_required:
            flags.append(_flag(
                "location_missing",
                "Sem GPS",
                "A leitura chegou sem coordenadas de coleta.",
                "warning",
            ))
    elif hydrometer.latitude is None or hydrometer.longitude is None:
        location_status = "missing_reference"
        flags.append(_flag(
            "location_reference_created",
            "Base de local criada",
            "Esta leitura definiu a localização-base do hidrômetro.",
            "info",
        ))
    else:
        allowed_radius = hydrometer.allowed_radius_meters or DEFAULT_ALLOWED_RADIUS_METERS
        distance = _distance_meters(hydrometer.latitude, hydrometer.longitude, latitude, longitude)
        if distance > allowed_radius * CRITICAL_DISTANCE_MULTIPLIER:
            location_status = "blocked_review"
            flags.append(_flag(
                "location_far",
                "Muito fora do raio",
                f"Coleta a {distance:.0f}m da base do hidrômetro; raio permitido {allowed_radius:.0f}m.",
                "danger",
            ))
        elif distance > allowed_radius:
            location_status = "warning"
            flags.append(_flag(
                "location_outside_radius",
                "Fora do raio",
                f"Coleta a {distance:.0f}m da base do hidrômetro; raio permitido {allowed_radius:.0f}m.",
                "warning",
            ))

    if location_accuracy_meters and location_accuracy_meters > LOW_ACCURACY_THRESHOLD_METERS:
        if location_status == "ok":
            location_status = "low_accuracy"
        flags.append(_flag(
            "location_low_accuracy",
            "GPS impreciso",
            f"Precisão informada pelo aparelho: {location_accuracy_meters:.0f}m.",
            "warning",
        ))

    consumption = current_value - previous_value
    if consumption < 0:
        limit = _rollover_limit(hydrometer)
        rollover_allowed = previous_value >= limit * ROLLOVER_PREVIOUS_THRESHOLD
        if rollover_allowed:
            consumption = (limit - previous_value) + current_value
            flags.append(_flag(
                "meter_rollover",
                "Virada do hidrômetro",
                f"Leitura anterior próxima do limite {limit:.0f}; consumo calculado por virada.",
                "info",
            ))
        elif anomaly_override_reason:
            flags.append(_flag(
                "reading_regression_override",
                "Leitura menor que anterior",
                "Leitura enviada como exceção e precisa de conferência manual.",
                "danger",
            ))
            consumption = 0.0
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Leitura atual menor que a anterior. Confira se o QR/hidrômetro está correto "
                    "ou registre uma exceção justificada."
                ),
            )

    return max(consumption, 0.0), location_status, distance, flags


async def _get_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


def _month_bounds(reference: date) -> tuple[datetime, datetime]:
    month_start = date(reference.year, reference.month, 1)
    if reference.month == 12:
        next_month = date(reference.year + 1, 1, 1)
    else:
        next_month = date(reference.year, reference.month + 1, 1)
    return (
        datetime.combine(month_start, datetime.min.time(), timezone.utc),
        datetime.combine(next_month, datetime.min.time(), timezone.utc),
    )


async def _ensure_cycle_accepts_new_reading(db: AsyncSession, hydrometer: Hydrometer, captured_at: datetime) -> None:
    customer = hydrometer.customer
    if not customer:
        return

    reference_date = captured_at.date()
    due_date = resolve_invoice_due_date(reference_date, customer.due_day)
    reference_month = f"{due_date.year}-{due_date.month:02d}"

    invoice_result = await db.execute(
        select(Invoice.id, Invoice.status)
        .where(
            Invoice.customer_id == customer.id,
            Invoice.reference_month == reference_month,
            Invoice.charge_type.in_(BILLING_CYCLE_CHARGE_TYPES),
            Invoice.status.in_(ACTIVE_INVOICE_STATUSES),
        )
        .limit(1)
    )
    existing_invoice = invoice_result.first()
    if existing_invoice:
        status = existing_invoice[1]
        if status == "paid":
            detail = "Este ciclo ja esta pago. O cliente so volta para leitura no proximo ciclo."
        else:
            detail = "Este ciclo ja possui fatura ativa. Nao registre uma nova leitura para o mesmo periodo."
        raise HTTPException(status_code=409, detail=detail)

    period_start, next_period_start = _month_bounds(reference_date)
    reading_result = await db.execute(
        select(Reading.id, Reading.status)
        .where(
            Reading.hydrometer_id == hydrometer.id,
            Reading.status.in_(ACTIVE_READING_STATUSES),
            Reading.captured_at >= period_start,
            Reading.captured_at < next_period_start,
        )
        .limit(1)
    )
    existing_reading = reading_result.first()
    if existing_reading:
        status = existing_reading[1]
        if status == "pending":
            detail = "Este hidrometro ja tem leitura em revisao neste ciclo."
        else:
            detail = "Este hidrometro ja tem leitura aprovada neste ciclo."
        raise HTTPException(status_code=409, detail=detail)


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
        selectinload(Reading.invoice),
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
            resp.is_installation = (
                r.invoice.charge_type == "installation"
                if r.invoice
                else r.hydrometer.last_reading_date is None
            )
            resp.charge_type = r.invoice.charge_type if r.invoice else "installation" if resp.is_installation else "water"
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
    Envia para GLM-OCR e retorna dados extraídos.
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

    vision_inference = None
    if data.vision_inference_id:
        vision_inference = await db.get(VisionInference, data.vision_inference_id)
        if (
            not vision_inference
            or vision_inference.collaborator_id != user.id
            or (vision_inference.hydrometer_id and vision_inference.hydrometer_id != hydrometer.id)
        ):
            raise HTTPException(status_code=400, detail="Inferência visual não pertence a esta leitura")
        vision_inference.hydrometer_id = hydrometer.id

    await _ensure_cycle_accepts_new_reading(db, hydrometer, data.captured_at)

    # Salva foto
    photo_url = save_photo_from_base64(data.photo_base64, prefix="reading")

    # OCR via GLM-OCR fica como veredito interno. Quando o colaborador digitou
    # a leitura, a resposta nao depende mais do OCR para seguir o fluxo.
    ocr_result = {"codigo": None, "leitura_m3": None, "confianca": 0.0}
    if data.current_value is None:
        try:
            ocr_result = await glm_ocr_service.extract_hydrometer_data(data.photo_base64)
        except Exception as e:
            # OCR falhou, mas a leitura ainda pode ser registrada manualmente
            logger.warning("OCR falhou: %s", e)

    current_value = data.current_value
    if current_value is None:
        current_value = ocr_result.get("leitura_m3") or 0.0

    created_location_reference = (
        hydrometer.latitude is None
        and hydrometer.longitude is None
        and data.latitude is not None
        and data.longitude is not None
    )
    if created_location_reference:
        hydrometer.latitude = data.latitude
        hydrometer.longitude = data.longitude
        hydrometer.location_source = "first_reading"

    consumption, location_status, distance, flags = _evaluate_reading(
        hydrometer=hydrometer,
        current_value=current_value,
        previous_value=hydrometer.last_reading_value,
        latitude=data.latitude,
        longitude=data.longitude,
        location_accuracy_meters=data.location_accuracy_meters,
        anomaly_override_reason=data.anomaly_override_reason,
    )
    if created_location_reference:
        flags.append(_flag(
            "location_reference_created",
            "Base de local criada",
            "Esta leitura definiu a localização-base do hidrômetro.",
            "info",
        ))

    # Cria leitura (status=pending, aguarda confirmação do colaborador)
    reading = Reading(
        hydrometer_id=data.hydrometer_id,
        collaborator_id=user.id,
        current_value=current_value,
        previous_value=hydrometer.last_reading_value,
        consumption=consumption,
        photo_url=photo_url,
        photo_extracted_code=data.confirmed_code or ocr_result.get("codigo"),
        photo_extracted_value=ocr_result.get("leitura_m3"),
        ocr_confidence=ocr_result.get("confianca"),
        vision_inference_id=data.vision_inference_id,
        latitude=data.latitude,
        longitude=data.longitude,
        location_accuracy_meters=data.location_accuracy_meters,
        distance_from_hydrometer_meters=distance,
        location_status=location_status,
        validation_flags=flags,
        anomaly_override_reason=data.anomaly_override_reason,
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

    consumption, location_status, distance, flags = _evaluate_reading(
        hydrometer=reading.hydrometer,
        current_value=data.current_value,
        previous_value=reading.previous_value,
        latitude=reading.latitude,
        longitude=reading.longitude,
        location_accuracy_meters=reading.location_accuracy_meters,
        anomaly_override_reason=reading.anomaly_override_reason,
    )
    reading.current_value = data.current_value
    reading.consumption = consumption
    reading.location_status = location_status
    reading.distance_from_hydrometer_meters = distance
    reading.validation_flags = flags
    if data.confirmed_code:
        reading.photo_extracted_code = data.confirmed_code

    await db.flush()
    await db.refresh(reading)
    return reading


@router.post("/{reading_id}/approve")
async def approve_reading(
    reading_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Gestor aprova leitura → calcula fatura → gera cobranca Efí.
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
    if reading.vision_inference_id:
        inference = await db.get(VisionInference, reading.vision_inference_id)
        if inference:
            inference.confirmed_value = reading.current_value
            inference.confirmed_at = inference.confirmed_at or reading.approved_at
            inference.was_correct = (
                inference.predicted_value is not None
                and abs(float(inference.predicted_value) - float(reading.current_value)) <= 0.01
            )
            inference.approved_for_training = True

    # Atualiza última leitura do hidrômetro
    hydrometer = reading.hydrometer
    is_installation_capture = hydrometer.last_reading_date is None
    hydrometer.last_reading_value = reading.current_value
    hydrometer.last_reading_date = datetime.now(timezone.utc)

    customer = hydrometer.customer

    # Determina data de vencimento da competencia atual.
    now = datetime.now(timezone.utc)
    today = now.date()
    due_date = resolve_invoice_due_date(today, customer.due_day)
    ref_month = f"{due_date.year}-{due_date.month:02d}"

    system_settings = await _get_system_settings(db)
    if is_installation_capture:
        amount = system_settings.installation_fee_amount
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
    if should_block_overdue_charges_for_late_reading(
        charge_type=charge_type,
        invoice_due_date=due_date,
        created_on=today,
    ):
        invoice.overdue_charges_allowed = False
        invoice.overdue_charge_blocked_reason = (
            "Leitura aprovada apos o vencimento da competencia. "
            "Multa e juros bloqueados por atraso operacional de leitura."
        )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)
    db.add(InvoiceEvent(
        invoice_id=invoice.id,
        user_id=admin.id,
        event_type="invoice_created_from_reading",
        previous_status=None,
        new_status=invoice.status,
        reason="Leitura aprovada gerou fatura",
        payload={
            "reading_id": str(reading.id),
            "charge_type": charge_type,
            "reference_month": ref_month,
            "is_installation": is_installation_capture,
        },
    ))

    # Gera cobranca Efí
    try:
        previous_status = invoice.status
        payment_due_date = payment_due_date_for_provider(invoice.due_date, today)
        boleto = await efi_service.emitir_cobranca(
            valor=amount,
            cpf_cnpj=customer.cpf_cnpj,
            nome=customer.name,
            email=customer.email or "",
            telefone=customer.phone,
            endereco=customer.address,
            numero=customer.number,
            bairro=customer.neighborhood,
            cidade=customer.city,
            uf=customer.state,
            cep=customer.zip_code,
            data_vencimento=payment_due_date,
            seu_numero=f"AQ-{str(invoice.id)[:8].upper()}",
            mensagem=boleto_message,
            multa_percentual=system_settings.late_fee_percent if invoice.overdue_charges_allowed else 0.0,
            juros_diario_percentual=system_settings.daily_interest_percent if invoice.overdue_charges_allowed else 0.0,
        )

        invoice.payment_provider = "efi"
        invoice.payment_due_date = payment_due_date
        invoice.efi_charge_id = boleto.get("charge_id")
        invoice.efi_status = boleto.get("status")
        invoice.efi_barcode = boleto.get("barcode")
        invoice.efi_payment_url = boleto.get("payment_url")
        invoice.efi_pdf_url = boleto.get("pdf_url")
        invoice.efi_pix_qrcode = boleto.get("pix_qrcode")
        invoice.efi_raw_response = boleto.get("raw")
        invoice.status = "sent"
        db.add(InvoiceEvent(
            invoice_id=invoice.id,
            user_id=admin.id,
            event_type="efi_charge_emitted",
            previous_status=previous_status,
            new_status=invoice.status,
            payload={
                "efi_charge_id": invoice.efi_charge_id,
                "efi_status": invoice.efi_status,
                "payment_due_date": invoice.payment_due_date.isoformat() if invoice.payment_due_date else None,
                "source": "reading_approval",
            },
        ))

    except Exception as e:
        logger.error("Erro ao gerar cobranca Efí: %s", e)
        db.add(InvoiceEvent(
            invoice_id=invoice.id,
            user_id=admin.id,
            event_type="efi_charge_failed",
            previous_status=invoice.status,
            new_status=invoice.status,
            reason="Falha ao emitir cobrança Efí na aprovação da leitura",
            payload={"error": str(e), "source": "reading_approval"},
        ))
        # Fatura criada mas sem cobranca — pode ser gerada depois

    await db.flush()
    if system_settings.auto_send_invoice_on_approval and (
        invoice.efi_pdf_url or invoice.efi_payment_url
    ):
        background_tasks.add_task(_send_invoice_generated_whatsapp, str(invoice.id))
    elif invoice.efi_pdf_url:
        background_tasks.add_task(_persist_invoice_boleto_document, str(invoice.id))

    return {
        "message": "Leitura aprovada e fatura gerada",
        "reading_id": str(reading.id),
        "invoice_id": str(invoice.id),
        "amount": amount,
        "consumption_m3": consumption_m3,
        "tariff_rate": tariff_rate,
        "charge_type": charge_type,
        "boleto_status": invoice.status,
        "due_date": invoice.due_date.isoformat(),
        "payment_due_date": invoice.payment_due_date.isoformat() if invoice.payment_due_date else None,
        "overdue_charges_allowed": invoice.overdue_charges_allowed,
    }


async def _persist_invoice_boleto_document(invoice_id: str) -> None:
    async with async_session_factory() as db:
        result = await db.execute(select(Invoice).where(Invoice.id == uuid.UUID(invoice_id)))
        invoice = result.scalar_one_or_none()
        if not invoice or not invoice.efi_pdf_url:
            return
        try:
            await get_or_create_boleto_pdf(
                db,
                invoice,
                efi_service.baixar_pdf,
                source="reading_approval",
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.warning("Persistencia do boleto %s no R2 ficou pendente: %s", invoice_id, exc)


async def _send_invoice_generated_whatsapp(invoice_id: str) -> None:
    await asyncio.sleep(0.5)
    async with async_session_factory() as db:
        result = await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.customer))
            .where(Invoice.id == uuid.UUID(invoice_id))
        )
        invoice = result.scalar_one_or_none()
        if not invoice or not invoice.customer or not invoice.customer.phone:
            return

        settings = await _get_system_settings(db)
        if not notification_flow_enabled(settings, "invoice_generated"):
            return

        base_message = render_invoice_customer_message(
            settings,
            charge_type=invoice.charge_type,
            customer_name=invoice.customer.name,
            amount=invoice.amount,
            due_date=invoice.due_date,
            reference_month=invoice.reference_month,
        )
        text = base_message
        if invoice.efi_payment_url and invoice.efi_payment_url not in text:
            text = f"{text}\n\nLink de pagamento: {invoice.efi_payment_url}"

        notification = Notification(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            channel="whatsapp",
            type=FLOW_NOTIFICATION_TYPES["invoice_generated"],
            status="queued",
            payload={"flow_key": "invoice_generated", "message": text, "mode": "document"},
        )
        db.add(notification)

        try:
            pdf_data = None
            try:
                pdf_data = await get_or_create_boleto_pdf(
                    db,
                    invoice,
                    efi_service.baixar_pdf,
                    source="reading_approval_whatsapp",
                )
            except Exception as exc:
                logger.warning("Nao foi possivel persistir PDF da fatura %s no R2: %s", invoice.id, exc)

            if pdf_data:
                wa_result = await whatsapp_service.send_invoice_document(
                    phone=invoice.customer.phone,
                    pdf_data=pdf_data,
                    filename=f"boleto_{str(invoice.id)[:8]}.pdf",
                    caption=text,
                )
                mode = "document"
            elif invoice.efi_payment_url:
                wa_result = await whatsapp_service.send_text(invoice.customer.phone, text)
                mode = "payment_link"
                notification.payload = {**(notification.payload or {}), "mode": mode}
            else:
                wa_result = {"status": "failed", "error": "Fatura sem PDF e sem link de pagamento."}
                mode = "missing_payment_file"
                notification.payload = {**(notification.payload or {}), "mode": mode}

            notification.status = (wa_result or {}).get("status") or "failed"
            notification.external_message_id = (wa_result or {}).get("message_id")
            notification.sent_at = datetime.now(timezone.utc)
            if (wa_result or {}).get("error"):
                notification.error_message = str(wa_result["error"])[:500]
            if notification.status == "sent":
                db.add(WhatsAppMessage(
                    customer_id=invoice.customer_id,
                    phone=invoice.customer.phone,
                    direction="outbound",
                    body=text,
                    external_message_id=notification.external_message_id,
                    status="sent",
                    payload={"flow_key": "invoice_generated", "invoice_id": str(invoice.id), "mode": mode},
                ))
            db.add(InvoiceEvent(
                invoice_id=invoice.id,
                event_type="whatsapp_invoice_sent" if notification.status == "sent" else "whatsapp_invoice_failed",
                previous_status=invoice.status,
                new_status=invoice.status,
                reason=notification.error_message,
                payload={
                    "mode": mode,
                    "message_id": notification.external_message_id,
                    "source": "reading_approval_auto_send",
                },
            ))
        except Exception as exc:
            notification.status = "failed"
            notification.error_message = str(exc)[:500]
            db.add(InvoiceEvent(
                invoice_id=invoice.id,
                event_type="whatsapp_invoice_failed",
                previous_status=invoice.status,
                new_status=invoice.status,
                reason=notification.error_message,
                payload={"source": "reading_approval_auto_send"},
            ))
            logger.warning("Falha no envio automatico da fatura %s: %s", invoice.id, exc)

        await db.commit()


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
