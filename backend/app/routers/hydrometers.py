"""Router de hidrometros - CRUD vinculado a clientes."""

import asyncio
import uuid
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.vision_inference import VisionInference
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.hydrometer import (
    HydrometerCreate,
    HydrometerIdentifyRequest,
    HydrometerIdentifyResponse,
    HydrometerListResponse,
    HydrometerDisconnectRequest,
    HydrometerQrResolveRequest,
    HydrometerResponse,
    HydrometerResolveCodeRequest,
    KimiVisionFeedbackRequest,
    HydrometerUpdate,
)
from app.services.hydrometer_codes import assign_numeric_code_if_needed, normalize_hydrometer_code
from app.services.glm_ocr import GlmOcrError, glm_ocr_service
from app.services.meter_vision import meter_vision_service
from app.utils.security import get_current_user, require_admin
from app.utils.storage import decode_base64_upload, save_binary

router = APIRouter(prefix="/hydrometers", tags=["Hidrometros"])


async def _fetch_hydrometer_response(db: AsyncSession, hydrometer_id: uuid.UUID) -> Hydrometer | None:
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.id == hydrometer_id)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=HydrometerListResponse)
async def list_hydrometers(
    customer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Hydrometer).options(selectinload(Hydrometer.customer))
    if customer_id:
        query = query.where(Hydrometer.customer_id == uuid.UUID(customer_id))
    query = query.order_by(Hydrometer.code)
    result = await db.execute(query)
    items = result.scalars().all()
    return HydrometerListResponse(items=items, total=len(items))


@router.post("/identify", response_model=HydrometerIdentifyResponse)
async def identify_hydrometer_from_photo(
    data: HydrometerIdentifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Extrai o codigo do hidrometro pela foto e tenta associar ao cadastro."""
    try:
        ocr_result = await glm_ocr_service.extract_hydrometer_data(data.photo_base64)
    except GlmOcrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    extracted_code = normalize_hydrometer_code(ocr_result.get("codigo"))

    if not extracted_code:
        return HydrometerIdentifyResponse(
            extracted_code=None,
            confidence=ocr_result.get("confianca"),
            matched=False,
        )

    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.code == extracted_code)
    )
    hydrometer = result.scalar_one_or_none()

    if not hydrometer:
        return HydrometerIdentifyResponse(
            extracted_code=extracted_code,
            confidence=ocr_result.get("confianca"),
            matched=False,
        )

    return HydrometerIdentifyResponse(
        extracted_code=extracted_code,
        confidence=ocr_result.get("confianca"),
        matched=True,
        hydrometer_id=hydrometer.id,
        hydrometer_code=hydrometer.code,
        qr_code_token=hydrometer.qr_code_token,
        customer_id=hydrometer.customer_id,
        customer_name=hydrometer.customer.name if hydrometer.customer else None,
        location_description=hydrometer.location_description,
        last_reading_value=hydrometer.last_reading_value,
        last_reading_date=hydrometer.last_reading_date,
        red_digits=hydrometer.red_digits,
        black_digits=hydrometer.black_digits,
        brand=hydrometer.brand,
        model=hydrometer.model,
    )


@router.post("/resolve-code", response_model=HydrometerIdentifyResponse)
async def resolve_hydrometer_code(
    data: HydrometerResolveCodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Valida o codigo digitado pelo colaborador sem depender do OCR."""
    code = normalize_hydrometer_code(data.code)
    if not code:
        raise HTTPException(status_code=400, detail="Digite um codigo numerico valido")

    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.code == code)
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        return HydrometerIdentifyResponse(extracted_code=code, confidence=None, matched=False)

    return HydrometerIdentifyResponse(
        extracted_code=code,
        confidence=1.0,
        matched=True,
        hydrometer_id=hydrometer.id,
        hydrometer_code=hydrometer.code,
        qr_code_token=hydrometer.qr_code_token,
        customer_id=hydrometer.customer_id,
        customer_name=hydrometer.customer.name if hydrometer.customer else None,
        location_description=hydrometer.location_description,
        last_reading_value=hydrometer.last_reading_value,
        last_reading_date=hydrometer.last_reading_date,
        red_digits=hydrometer.red_digits,
        black_digits=hydrometer.black_digits,
        brand=hydrometer.brand,
        model=hydrometer.model,
    )


@router.post("/resolve-qr", response_model=HydrometerIdentifyResponse)
async def resolve_hydrometer_qr(
    data: HydrometerQrResolveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resolve o QR Code unico do cliente/hidrometro capturado no app mobile."""
    token = data.qr_code_token.strip()
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where((Hydrometer.qr_code_token == token) | (Hydrometer.code == token))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        return HydrometerIdentifyResponse(extracted_code=None, confidence=None, matched=False)

    return HydrometerIdentifyResponse(
        extracted_code=hydrometer.code,
        confidence=1.0,
        matched=True,
        hydrometer_id=hydrometer.id,
        hydrometer_code=hydrometer.code,
        qr_code_token=hydrometer.qr_code_token,
        customer_id=hydrometer.customer_id,
        customer_name=hydrometer.customer.name if hydrometer.customer else None,
        location_description=hydrometer.location_description,
        last_reading_value=hydrometer.last_reading_value,
        last_reading_date=hydrometer.last_reading_date,
        red_digits=hydrometer.red_digits,
        black_digits=hydrometer.black_digits,
        brand=hydrometer.brand,
        model=hydrometer.model,
    )


@router.get("/{hydrometer_id}/qr-code.svg")
async def download_hydrometer_qr_code(
    hydrometer_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Exporta o QR Code do hidrometro em SVG para impressao."""
    result = await db.execute(select(Hydrometer).where(Hydrometer.id == uuid.UUID(hydrometer_id)))
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrometro nao encontrado")

    import qrcode
    import qrcode.image.svg

    image = qrcode.make(hydrometer.qr_code_token, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Content-Disposition": f"attachment; filename=qr_hidrometro_{hydrometer.code}.svg"},
    )


@router.post("/vision-feedback")
async def store_kimi_vision_feedback(
    data: KimiVisionFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Registra o veredito interno do GLM-OCR contra o valor digitado pelo colaborador."""
    predicted_code = normalize_hydrometer_code(data.predicted_code)
    confirmed_code = normalize_hydrometer_code(data.confirmed_code)
    was_correct = None
    if data.stage == "code" and confirmed_code:
        was_correct = predicted_code == confirmed_code
    elif data.stage in ("reading", "dev_test") and data.confirmed_value is not None and data.predicted_value is not None:
        was_correct = abs(float(data.confirmed_value) - float(data.predicted_value)) <= 0.01

    lesson = "Aguardando confirmacao humana."
    divergence_reason = data.divergence_reason
    if was_correct is True:
        lesson = "Veredito conferiu com a digitacao do colaborador."
    elif was_correct is False:
        divergence_reason = divergence_reason or (
            "Possivel confusao visual por reflexo, foco, recorte, sujeira, digitos vermelhos/pretos "
            "ou formato diferente do mostrador cadastrado."
        )
        lesson = (
            "Divergencia registrada: revisar foco, recorte, reflexo, sujeira ou digitos parecidos "
            "nas proximas leituras."
        )

    inference = await db.get(VisionInference, data.inference_id) if data.inference_id else None
    if inference is None:
        inference = VisionInference(
            hydrometer_id=data.hydrometer_id,
            collaborator_id=user.id,
            stage=data.stage,
            model_version="legacy-feedback",
            predicted_code=predicted_code,
            predicted_value=data.predicted_value,
            confidence=data.confidence or 0.0,
            auto_fill_allowed=False,
            red_digits=data.red_digits,
            black_digits=data.black_digits,
            hydrometer_brand=data.hydrometer_brand,
            hydrometer_model=data.hydrometer_model,
        )
        db.add(inference)
    inference.confirmed_code = confirmed_code
    inference.confirmed_value = data.confirmed_value
    inference.was_correct = was_correct
    inference.divergence_reason = divergence_reason
    inference.confirmed_at = datetime.now(timezone.utc)
    await db.flush()
    return {"id": str(inference.id), "was_correct": was_correct, "lesson": lesson}


@router.post("/vision-verdict")
async def kimi_vision_verdict(
    data: HydrometerIdentifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Executa o motor local especializado; GLM, quando habilitado, fica apenas em sombra."""
    frames = [data.photo_base64, *data.frames_base64[:4]]
    results = await asyncio.gather(*[
        asyncio.to_thread(
            meter_vision_service.analyze,
            frame,
            red_digits=data.red_digits,
            black_digits=data.black_digits,
            previous_value=data.previous_value,
        )
        for frame in frames
    ])
    best_index, vision_result = max(
        enumerate(results),
        key=lambda item: (
            bool(item[1].quality.get("usable")),
            item[1].confidence,
            -float(item[1].quality.get("blur", 1.0)),
        ),
    )
    selected_frame = frames[best_index]
    inference_id = uuid.uuid4()
    original_key = None
    rectified_key = None
    try:
        ext, raw, content_type = decode_base64_upload(selected_frame, "jpg")
        object_prefix = f"vision/{datetime.now(timezone.utc):%Y/%m/%d}/{inference_id}"
        uploads = [
            asyncio.to_thread(
                save_binary,
                raw,
                f"{object_prefix}/original.{ext}",
                content_type,
            )
        ]
        if vision_result.rectified_jpeg:
            uploads.append(
                asyncio.to_thread(
                    save_binary,
                    vision_result.rectified_jpeg,
                    f"{object_prefix}/rectified.jpg",
                    "image/jpeg",
                )
            )
        uploaded = await asyncio.gather(*uploads)
        original_key = uploaded[0]
        rectified_key = uploaded[1] if len(uploaded) > 1 else None
    except Exception as exc:
        vision_result.flags.append("artifact_storage_failed")
        vision_result.quality["storage_error"] = str(exc)[:240]

    shadow = None
    from app.config import get_settings
    if get_settings().vision_glm_shadow_enabled:
        try:
            shadow_result = await glm_ocr_service.extract_hydrometer_data(data.photo_base64)
            shadow = {
                "predicted_code": normalize_hydrometer_code(shadow_result.get("codigo")),
                "predicted_value": shadow_result.get("leitura_m3"),
                "confidence": shadow_result.get("confianca"),
            }
        except GlmOcrError as exc:
            shadow = {"error": str(exc)}

    inference = VisionInference(
        id=inference_id,
        hydrometer_id=data.hydrometer_id,
        collaborator_id=user.id,
        stage=data.stage,
        original_object_key=original_key,
        rectified_object_key=rectified_key,
        model_version=vision_result.model_version,
        predicted_code=vision_result.predicted_code,
        predicted_value=vision_result.predicted_value,
        confidence=vision_result.confidence,
        auto_fill_allowed=vision_result.auto_fill_allowed,
        quality={**vision_result.quality, **({"glm_shadow": shadow} if shadow else {})},
        digits=vision_result.digits,
        alternatives=vision_result.alternatives,
        flags=vision_result.flags,
        red_digits=data.red_digits,
        black_digits=data.black_digits,
        hydrometer_brand=data.hydrometer_brand,
        hydrometer_model=data.hydrometer_model,
    )
    inference.quality = {**(inference.quality or {}), "burst_frames": len(frames), "selected_frame": best_index}
    db.add(inference)
    await db.flush()
    return {"inference_id": str(inference.id), **vision_result.public_dict(), "glm_shadow": shadow}


@router.get("/ocr-memory/summary")
@router.get("/kimi-memory/summary")
async def kimi_memory_summary(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    total = (await db.execute(select(func.count()).select_from(VisionInference))).scalar() or 0
    correct = (
        await db.execute(
            select(func.count()).select_from(VisionInference).where(VisionInference.was_correct.is_(True))
        )
    ).scalar() or 0
    wrong = (
        await db.execute(
            select(func.count()).select_from(VisionInference).where(VisionInference.was_correct.is_(False))
        )
    ).scalar() or 0
    recent_result = await db.execute(
        select(VisionInference).order_by(VisionInference.created_at.desc()).limit(8)
    )
    recent = recent_result.scalars().all()
    accuracy = round((correct / (correct + wrong)) * 100, 1) if correct + wrong else 0.0
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
        "recent": [
            {
                "id": str(item.id),
                "stage": item.stage,
                "predicted_code": item.predicted_code,
                "confirmed_code": item.confirmed_code,
                "predicted_value": item.predicted_value,
                "confirmed_value": item.confirmed_value,
                "red_digits": item.red_digits,
                "black_digits": item.black_digits,
                "hydrometer_brand": item.hydrometer_brand,
                "hydrometer_model": item.hydrometer_model,
                "was_correct": item.was_correct,
                "lesson": "Amostra aprovada para treino." if item.approved_for_training else "Aguardando aprovação da leitura.",
                "reasoning_log": f"Modelo {item.model_version}; confianca={item.confidence:.3f}",
                "divergence_reason": item.divergence_reason,
                "created_at": item.created_at,
            }
            for item in recent
        ],
    }


async def _get_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


@router.post("/{hydrometer_id}/disconnect", response_model=HydrometerResponse)
async def disconnect_hydrometer(
    hydrometer_id: str,
    data: HydrometerDisconnectRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.id == uuid.UUID(hydrometer_id))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrometro nao encontrado")

    hydrometer.is_active = False
    hydrometer.disconnected_at = datetime.now(timezone.utc)
    hydrometer.disconnection_reason = data.reason or "Desligado por falta de pagamento"
    if hydrometer.customer:
        hydrometer.customer.status = "disconnected"
    await db.flush()
    updated = await _fetch_hydrometer_response(db, hydrometer.id)
    return updated or hydrometer


@router.post("/{hydrometer_id}/reconnect", response_model=HydrometerResponse)
async def reconnect_hydrometer(
    hydrometer_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.id == uuid.UUID(hydrometer_id))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrometro nao encontrado")

    settings = await _get_system_settings(db)
    hydrometer.is_active = True
    hydrometer.reconnected_at = datetime.now(timezone.utc)
    if hydrometer.customer:
        hydrometer.customer.status = "active"
        invoice = Invoice(
            customer_id=hydrometer.customer_id,
            amount=settings.reconnection_fee_amount,
            original_amount=settings.reconnection_fee_amount,
            reference_month=datetime.now(timezone.utc).strftime("%Y-%m"),
            due_date=datetime.now(timezone.utc).date(),
            consumption_m3=0.0,
            tariff_rate=0.0,
            charge_type="reconnection",
            status="pending",
        )
        db.add(invoice)
    await db.flush()
    updated = await _fetch_hydrometer_response(db, hydrometer.id)
    return updated or hydrometer


@router.get("/{hydrometer_id}", response_model=HydrometerResponse)
async def get_hydrometer(
    hydrometer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.id == uuid.UUID(hydrometer_id))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrometro nao encontrado")
    return hydrometer


@router.post("", response_model=HydrometerResponse, status_code=201)
async def create_hydrometer(
    data: HydrometerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    customer_result = await db.execute(select(Customer).where(Customer.id == data.customer_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    try:
        target_code = await assign_numeric_code_if_needed(db, data.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if data.red_digits not in (2, 3):
        raise HTTPException(status_code=400, detail="Digitos vermelhos devem ser 2 ou 3")
    if data.black_digits is not None and data.black_digits < 1:
        raise HTTPException(status_code=400, detail="Digitos pretos deve ser maior que zero")

    hydrometer = Hydrometer(
        customer_id=data.customer_id,
        code=target_code,
        brand=data.brand,
        model=data.model,
        red_digits=data.red_digits,
        black_digits=data.black_digits,
        location_description=data.location_description,
        latitude=data.latitude,
        longitude=data.longitude,
        allowed_radius_meters=data.allowed_radius_meters,
        location_required=data.location_required,
        location_source="manual" if data.latitude is not None and data.longitude is not None else None,
        last_reading_value=data.initial_reading,
    )
    db.add(hydrometer)
    await db.flush()
    created = await _fetch_hydrometer_response(db, hydrometer.id)
    return created or hydrometer


@router.patch("/{hydrometer_id}", response_model=HydrometerResponse)
async def update_hydrometer(
    hydrometer_id: str,
    data: HydrometerUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(Hydrometer)
        .options(selectinload(Hydrometer.customer))
        .where(Hydrometer.id == uuid.UUID(hydrometer_id))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrometro nao encontrado")

    update_data = data.model_dump(exclude_unset=True)
    if "code" in update_data:
        try:
            update_data["code"] = await assign_numeric_code_if_needed(
                db,
                update_data["code"],
                hydrometer.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "red_digits" in update_data and update_data["red_digits"] not in (2, 3):
        raise HTTPException(status_code=400, detail="Digitos vermelhos devem ser 2 ou 3")
    if "black_digits" in update_data and update_data["black_digits"] is not None and update_data["black_digits"] < 1:
        raise HTTPException(status_code=400, detail="Digitos pretos deve ser maior que zero")
    if "allowed_radius_meters" in update_data and update_data["allowed_radius_meters"] is not None and update_data["allowed_radius_meters"] < 10:
        raise HTTPException(status_code=400, detail="Raio permitido deve ser pelo menos 10 metros")
    if "last_reading_value" in update_data and update_data["last_reading_value"] is not None:
        hydrometer.last_reading_date = datetime.now(timezone.utc)
    if (
        ("latitude" in update_data or "longitude" in update_data)
        and update_data.get("latitude", hydrometer.latitude) is not None
        and update_data.get("longitude", hydrometer.longitude) is not None
    ):
        update_data["location_source"] = "manual"

    for field, value in update_data.items():
        setattr(hydrometer, field, value)

    await db.flush()
    updated = await _fetch_hydrometer_response(db, hydrometer.id)
    return updated or hydrometer
