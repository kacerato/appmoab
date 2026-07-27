"""
Router de Leituras — Upload de foto, OCR, validação e aprovação.
"""

import logging
import math
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_factory, get_db
from app.models.reading import Reading
from app.models.reading_cycle import ReadingCycle
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.invoice_event import InvoiceEvent
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.models.vision_inference import VisionInference
from app.schemas.reading import (
    ReadingApprove, ReadingCreate, ReadingOCRResult, ReadingConfirm,
    ReadingReject, ReadingResponse, ReadingListResponse,
)
from app.services.glm_ocr import glm_ocr_service
from app.services.billing import calculate_billing
from app.services.billing_policy import (
    payment_due_date_for_provider,
    should_block_overdue_charges_for_late_reading,
)
from app.services.efi_api import efi_service
from app.services.invoice_documents import get_or_create_boleto_pdf
from app.services.invoice_whatsapp import dispatch_invoice_notification_task, enqueue_invoice_whatsapp
from app.services.reading_cycles import (
    advance_after_approval,
    ensure_actionable_cycle,
    is_first_official_reading,
    promote_cycle_to_installation,
)
from app.utils.security import get_current_user, require_admin
from app.utils.storage import build_public_upload_url, save_photo_from_base64

router = APIRouter(prefix="/readings", tags=["Leituras"])
logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_RADIUS_METERS = 80.0
CRITICAL_DISTANCE_MULTIPLIER = 4
LOW_ACCURACY_THRESHOLD_METERS = 50.0
ROLLOVER_PREVIOUS_THRESHOLD = 0.90
ACTIVE_READING_STATUSES = ("pending", "approved")


def _installation_billing_values(settings: SystemSetting) -> tuple[float, float, float]:
    """Taxa fixa: nunca usa leitura-base nem consumo para formar o valor."""
    return float(settings.installation_fee_amount), 0.0, 0.0


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
    location_status, distance, flags = _evaluate_location(
        hydrometer=hydrometer,
        latitude=latitude,
        longitude=longitude,
        location_accuracy_meters=location_accuracy_meters,
    )

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


def _evaluate_location(
    *,
    hydrometer: Hydrometer,
    latitude: float | None,
    longitude: float | None,
    location_accuracy_meters: float | None,
) -> tuple[str, float | None, list[dict]]:
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
            "location_reference_pending",
            "Base de local pendente",
            "Ao aprovar, esta captura definira a localização-base do hidrômetro.",
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

    return location_status, distance, flags


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
    customer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista leituras com filtros — usado na fila de aprovação."""
    query = select(Reading).options(
        selectinload(Reading.hydrometer).selectinload(Hydrometer.customer),
        selectinload(Reading.collaborator),
        selectinload(Reading.invoice),
        selectinload(Reading.vision_inference),
    )

    if status:
        query = query.where(Reading.status == status)
    if hydrometer_id:
        query = query.where(Reading.hydrometer_id == uuid.UUID(hydrometer_id))
    if customer_id:
        query = query.join(Reading.hydrometer).where(
            Hydrometer.customer_id == uuid.UUID(customer_id)
        )

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
        if r.vision_inference:
            inference = r.vision_inference
            resp.vision_predicted_code = inference.predicted_code
            resp.vision_predicted_value = inference.predicted_value
            resp.vision_confidence = inference.calibrated_confidence if inference.calibrated_confidence is not None else inference.confidence
            resp.vision_decision = inference.decision
            resp.vision_digits = inference.digits or []
            resp.vision_alternatives = inference.alternatives or []
            resp.vision_quality = inference.quality or {}
            resp.vision_flags = inference.flags or []
            resp.vision_rectified_url = build_public_upload_url(inference.rectified_object_key) if inference.rectified_object_key else None
            resp.vision_original_url = build_public_upload_url(inference.original_object_key) if inference.original_object_key else None
            resp.vision_frame_urls = [
                build_public_upload_url(key)
                for key in (inference.frame_object_keys or [])
                if key
            ]
            metadata = inference.capture_metadata or {}
            selected_index = metadata.get("selected_frame_index", metadata.get("selected_frame"))
            resp.vision_selected_frame_index = (
                int(selected_index) if isinstance(selected_index, (int, float)) else None
            )
        if r.hydrometer and r.hydrometer.customer:
            resp.customer_name = r.hydrometer.customer.name
            resp.customer_id = r.hydrometer.customer.id
            resp.is_installation = r.reading_kind == "installation"
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

    cycle = await ensure_actionable_cycle(db, hydrometer, lock=True)
    if data.cycle_id and cycle.id != data.cycle_id:
        raise HTTPException(
            status_code=409,
            detail="Esta tarefa de leitura foi atualizada. Reabra a rota antes de enviar a captura.",
        )
    if cycle.status == "pending_review":
        raise HTTPException(
            status_code=409,
            detail="Este ciclo ja possui uma captura aguardando conferencia.",
        )
    active_reading = (
        await db.execute(
            select(Reading.id)
            .where(
                Reading.cycle_id == cycle.id,
                Reading.status.in_(ACTIVE_READING_STATUSES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_reading:
        raise HTTPException(
            status_code=409,
            detail="Este ciclo ja possui uma leitura ativa.",
        )

    # Salva foto
    photo_url = save_photo_from_base64(data.photo_base64, prefix="reading")

    # A inferencia visual e apenas uma sugestao. O valor oficial so sera
    # definido por um gestor no endpoint de aprovacao.
    ocr_result = {"codigo": None, "leitura_m3": None, "confianca": 0.0}
    if vision_inference:
        ocr_result = {
            "codigo": vision_inference.predicted_code,
            "leitura_m3": vision_inference.predicted_value,
            "confianca": (
                vision_inference.calibrated_confidence
                if vision_inference.calibrated_confidence is not None
                else vision_inference.confidence
            ),
        }
    elif data.current_value is not None:
        # APK antigo: preserva o que foi digitado como sugestao legada, sem
        # consolidar current_value/consumption.
        ocr_result = {
            "codigo": None,
            "leitura_m3": data.current_value,
            "confianca": 0.0,
        }
    else:
        try:
            ocr_result = await glm_ocr_service.extract_hydrometer_data(data.photo_base64)
        except Exception as e:
            # OCR falhou, mas a captura ainda segue para conferencia no painel.
            logger.warning("OCR falhou: %s", e)

    location_status, distance, flags = _evaluate_location(
        hydrometer=hydrometer,
        latitude=data.latitude,
        longitude=data.longitude,
        location_accuracy_meters=data.location_accuracy_meters,
    )

    # Cria captura pendente; leitura e consumo ainda nao existem oficialmente.
    reading = Reading(
        hydrometer_id=data.hydrometer_id,
        collaborator_id=user.id,
        current_value=None,
        previous_value=hydrometer.last_reading_value,
        consumption=None,
        photo_url=photo_url,
        photo_extracted_code=ocr_result.get("codigo") or data.confirmed_code,
        photo_extracted_value=ocr_result.get("leitura_m3"),
        ocr_confidence=ocr_result.get("confianca"),
        vision_inference_id=data.vision_inference_id,
        cycle_id=cycle.id,
        reference_month=cycle.reference_month,
        reading_kind=cycle.cycle_type,
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
    cycle.status = "pending_review"
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
    user: User = Depends(require_admin),
):
    """Compatibilidade: somente gestor pode alterar o valor pendente."""
    result = await db.execute(
        select(Reading)
        .options(selectinload(Reading.hydrometer))
        .where(Reading.id == uuid.UUID(reading_id))
        .with_for_update()
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")
    if reading.status != "pending":
        raise HTTPException(status_code=409, detail="Somente capturas pendentes podem ser ajustadas")

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
    data: ReadingApprove | None = None,
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
            selectinload(Reading.vision_inference),
            selectinload(Reading.cycle),
        )
        .where(Reading.id == uuid.UUID(reading_id))
        .with_for_update()
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")
    if reading.status != "pending":
        raise HTTPException(status_code=400, detail=f"Leitura já está '{reading.status}'")

    hydrometer = reading.hydrometer
    cycle = reading.cycle
    if cycle is None:
        cycle = await ensure_actionable_cycle(db, hydrometer, lock=True)
        reading.cycle_id = cycle.id
        reading.reference_month = cycle.reference_month

    first_official_reading = await is_first_official_reading(
        db,
        hydrometer.id,
        exclude_reading_id=reading.id,
    )
    if first_official_reading:
        cycle = await promote_cycle_to_installation(db, cycle)
        reading.cycle_id = cycle.id
        reading.reference_month = cycle.reference_month
    is_installation_capture = first_official_reading or cycle.cycle_type == "installation"
    reading.reading_kind = "installation" if is_installation_capture else "water"

    inference = reading.vision_inference
    suggested_value = (
        inference.predicted_value
        if inference and inference.predicted_value is not None
        else reading.photo_extracted_value
    )
    chosen_value = data.current_value if data and data.current_value is not None else suggested_value
    if chosen_value is None:
        raise HTTPException(status_code=422, detail="Informe a leitura confirmada no dashboard")

    adjustment_reason = data.adjustment_reason.strip() if data and data.adjustment_reason else None
    if suggested_value is not None and abs(float(chosen_value) - float(suggested_value)) > 0.0005 and not adjustment_reason:
        adjustment_reason = "Valor ajustado manualmente no dashboard"

    if is_installation_capture:
        location_status, distance, flags = _evaluate_location(
            hydrometer=hydrometer,
            latitude=reading.latitude,
            longitude=reading.longitude,
            location_accuracy_meters=reading.location_accuracy_meters,
        )
        consumption = 0.0
        flags = [
            flag
            for flag in flags
            if flag.get("code") not in {"consumption_spike", "meter_regression"}
        ] + [_flag(
            "installation_baseline",
            "Leitura-base de instalação",
            "Este valor inicia o hidrômetro e não representa consumo faturável.",
            "info",
        )]
    else:
        consumption, location_status, distance, flags = _evaluate_reading(
            hydrometer=hydrometer,
            current_value=float(chosen_value),
            previous_value=reading.previous_value,
            latitude=reading.latitude,
            longitude=reading.longitude,
            location_accuracy_meters=reading.location_accuracy_meters,
            anomaly_override_reason=adjustment_reason or reading.anomaly_override_reason,
        )

    reading.current_value = float(chosen_value)
    reading.consumption = consumption
    reading.location_status = location_status
    reading.distance_from_hydrometer_meters = distance
    reading.validation_flags = flags
    reading.review_adjustment_reason = adjustment_reason

    # Aprova leitura
    reading.status = "approved"
    reading.approved_by = admin.id
    reading.approved_at = datetime.now(timezone.utc)
    if inference:
        inference.confirmed_value = reading.current_value
        inference.confirmed_at = inference.confirmed_at or reading.approved_at
        if data and data.confirmed_code:
            inference.confirmed_code = data.confirmed_code
        elif not inference.confirmed_code:
            red_digits = inference.red_digits if inference.red_digits is not None else reading.hydrometer.red_digits
            black_digits = inference.black_digits if inference.black_digits is not None else (reading.hydrometer.black_digits or 4)
            total_digits = max(3, min(red_digits + black_digits, 10))
            inference.confirmed_code = str(int(round(reading.current_value * (10 ** red_digits)))).zfill(total_digits)
        inference.was_correct = (
            inference.predicted_value is not None
            and abs(float(inference.predicted_value) - float(reading.current_value)) <= 0.01
        )
        inference.approved_for_training = True

    # Atualiza última leitura do hidrômetro
    if hydrometer.latitude is None and hydrometer.longitude is None and reading.latitude is not None and reading.longitude is not None:
        hydrometer.latitude = reading.latitude
        hydrometer.longitude = reading.longitude
        hydrometer.location_source = "approved_first_reading"
        reading.location_status = "reference_created"
        reading.validation_flags = [
            flag for flag in reading.validation_flags if flag.get("code") != "location_reference_pending"
        ] + [_flag(
            "location_reference_created",
            "Base de local criada",
            "A captura aprovada definiu a localização-base do hidrômetro.",
            "info",
        )]
    hydrometer.last_reading_value = reading.current_value
    hydrometer.last_reading_date = reading.captured_at

    customer = hydrometer.customer

    # A competencia pertence ao ciclo, nao ao dia em que o gestor aprovou.
    now = datetime.now(timezone.utc)
    today = now.date()
    due_date = cycle.due_date
    ref_month = cycle.reference_month

    system_settings = await _get_system_settings(db)
    if is_installation_capture:
        amount, consumption_m3, tariff_rate = _installation_billing_values(system_settings)
        charge_type = "installation"
        boleto_message = f"Instalacao do hidrometro {hydrometer.code} - Ref: {ref_month}"
    else:
        billing = await calculate_billing(db, reading.consumption)
        amount = billing.final_amount
        consumption_m3 = billing.consumption_m3
        tariff_rate = billing.tariff_rate
        charge_type = "water"
        boleto_message = f"Consumo: {billing.consumption_m3:.2f}m³ - Ref: {ref_month}"

    existing_invoice = (
        await db.execute(select(Invoice.id).where(Invoice.reading_id == reading.id).limit(1))
    ).scalar_one_or_none()
    if existing_invoice:
        raise HTTPException(status_code=409, detail="Esta leitura ja possui fatura")

    # Cria fatura
    invoice = Invoice(
        customer_id=customer.id,
        reading_id=reading.id,
        cycle_id=cycle.id,
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
    await advance_after_approval(db, hydrometer, cycle)
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
    notification = None
    if system_settings.auto_send_invoice_on_approval:
        notification = await enqueue_invoice_whatsapp(db, invoice, source="reading_approval")
    if notification:
        background_tasks.add_task(dispatch_invoice_notification_task, str(notification.id))
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
        "whatsapp_status": notification.status if notification else "disabled",
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


@router.post("/{reading_id}/reject")
async def reject_reading(
    reading_id: str,
    data: ReadingReject,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Gestor rejeita leitura com motivo."""
    result = await db.execute(
        select(Reading)
        .options(selectinload(Reading.cycle))
        .where(Reading.id == uuid.UUID(reading_id))
        .with_for_update()
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")
    if reading.status != "pending":
        raise HTTPException(status_code=409, detail="Somente capturas pendentes podem ser rejeitadas")

    reading.status = "rejected"
    reading.rejection_reason = data.reason
    reading.approved_by = admin.id
    reading.approved_at = datetime.now(timezone.utc)
    if reading.cycle:
        reading.cycle.status = "recapture_required"
    await db.flush()

    return {"message": "Leitura rejeitada", "reading_id": str(reading.id)}
