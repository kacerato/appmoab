"""Router de hidrometros - CRUD vinculado a clientes."""

import asyncio
import uuid
from collections import Counter
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
from app.services.meter_vision import VisionResult, meter_vision_service
from app.services.reading_cycles import ensure_actionable_cycle
from app.services.vision_decision import fuse_burst_results
from app.utils.security import get_current_user, require_admin
from app.utils.storage import build_public_upload_url, decode_base64_upload, save_binary

router = APIRouter(prefix="/hydrometers", tags=["Hidrometros"])


def _validate_manual_base_adjustment(hydrometer: Hydrometer, update_data: dict) -> None:
    if (
        "last_reading_value" in update_data
        and update_data["last_reading_value"] is not None
        and hydrometer.last_reading_date is None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "A instalacao ainda nao foi concluida. Envie foto e local pelo app "
                "e aprove a captura no painel para criar a leitura-base."
            ),
        )


def _meter_result_code(result: VisionResult, total_digits: int, red_digits: int) -> int | None:
    if result.predicted_value is None:
        return None
    return int(round(float(result.predicted_value) * (10 ** max(red_digits, 0)))) % (10 ** total_digits)


def _apply_burst_consensus(
    results: list[VisionResult],
    *,
    selected_index: int,
    red_digits: int,
    black_digits: int,
    previous_value: float | None = None,
    hydrometer_brand: str | None = None,
    hydrometer_model: str | None = None,
) -> tuple[int, VisionResult]:
    return fuse_burst_results(
        results,
        selected_index=selected_index,
        red_digits=red_digits,
        black_digits=black_digits,
        previous_value=previous_value,
        hydrometer_brand=hydrometer_brand,
        hydrometer_model=hydrometer_model,
    )


def _has_stable_visual_pair(results: list[VisionResult], *, red_digits: int, black_digits: int) -> bool:
    total_digits = max(3, min(int(red_digits) + int(black_digits), 10))
    codes = []
    for result in results:
        if result.decision == "recapture" or not result.quality.get("usable", True):
            continue
        code = _meter_result_code(result, total_digits, red_digits)
        if code is not None:
            codes.append(code)
    return bool(codes and Counter(codes).most_common(1)[0][1] >= 2)


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

    has_confirmed_label = bool(confirmed_code) or data.confirmed_value is not None
    training_requested = data.approve_for_training
    if training_requested is None:
        training_requested = data.stage == "dev_test" and has_confirmed_label
    training_approved = bool(training_requested and has_confirmed_label)
    dataset_status = (
        "approved_for_training"
        if training_approved
        else "diagnostic_confirmed"
        if has_confirmed_label
        else "diagnostic_pending_label"
    )

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
            decision="confirm",
            red_digits=data.red_digits,
            black_digits=data.black_digits,
            hydrometer_brand=data.hydrometer_brand,
            hydrometer_model=data.hydrometer_model,
        )
        db.add(inference)
    capture_quality = inference.quality or {}
    localization = capture_quality.get("display_detection") or {}
    localization_valid = bool(
        inference.rectified_object_key
        and localization.get("localization_valid")
    )
    if training_approved and not localization_valid:
        training_approved = False
        inference.approved_for_training = False
        dataset_status = "capture_review_required"
        divergence_reason = divergence_reason or (
            "Amostra sem localizacao validada do visor; revisar o vinculo entre foto, recorte e valor confirmado."
        )
        lesson = "Confirmacao preservada para diagnostico, mas bloqueada no treinamento ate revisar o recorte."
    inference.confirmed_code = confirmed_code
    inference.confirmed_value = data.confirmed_value
    inference.was_correct = was_correct
    inference.divergence_reason = divergence_reason
    inference.confirmed_at = datetime.now(timezone.utc)
    inference.slot_labels = data.slot_labels or inference.slot_labels
    if training_approved:
        inference.approved_for_training = True
        inference.dataset_version = "aqua-meter-training-v2"
    elif data.approve_for_training is False:
        inference.approved_for_training = False
    inference.quality = {
        **(inference.quality or {}),
        "dataset_source": data.stage,
        "dataset_status": dataset_status,
        "training_requested": bool(training_requested),
        "has_confirmed_label": has_confirmed_label,
        "localization_valid": localization_valid,
    }
    await db.flush()
    return {
        "id": str(inference.id),
        "was_correct": was_correct,
        "lesson": lesson,
        "approved_for_training": inference.approved_for_training,
        "dataset_status": dataset_status,
    }


@router.post("/vision-quality")
async def inspect_vision_capture(
    data: HydrometerIdentifyRequest,
    user: User = Depends(get_current_user),
):
    """Valida foco, reflexo, distância e perspectiva sem executar OCR."""
    del user
    return await asyncio.to_thread(
        meter_vision_service.inspect_capture,
        data.photo_base64,
        red_digits=data.red_digits,
        black_digits=data.black_digits,
        guide_crop=(
            (data.frame_metadata[0].get("guide_crop") if data.frame_metadata else None)
            or (data.capture_metadata or {}).get("guide_crop")
        ),
    )


@router.post("/vision-verdict")
async def kimi_vision_verdict(
    data: HydrometerIdentifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Executa o motor local especializado; GLM, quando habilitado, fica apenas em sombra."""
    frames = [data.photo_base64, *data.frames_base64[:7]]
    frame_guide_crops = []
    for index in range(len(frames)):
        frame_metadata = data.frame_metadata[index] if index < len(data.frame_metadata) else {}
        guide_crop = frame_metadata.get("guide_crop") if isinstance(frame_metadata, dict) else None
        if index == 0 and guide_crop is None:
            guide_crop = (data.capture_metadata or {}).get("guide_crop")
        frame_guide_crops.append(guide_crop)
    # O clique principal recebe OCR completo. Os demais quadros começam pela
    # análise leve; se dois deles concordarem, repetir RapidOCR só aumentaria a
    # latência. Sem um par estável, o fallback comprovado sonda todos os demais.
    expensive_probe_indexes = {0}
    results = await asyncio.gather(*[
        asyncio.to_thread(
            meter_vision_service.analyze,
            frame,
            red_digits=data.red_digits,
            black_digits=data.black_digits,
            previous_value=data.previous_value,
            expensive_ocr=index in expensive_probe_indexes,
            hydrometer_brand=data.hydrometer_brand,
            hydrometer_model=data.hydrometer_model,
            guide_crop=frame_guide_crops[index],
        )
        for index, frame in enumerate(frames)
    ])
    best_index, vision_result = max(
        enumerate(results),
        key=lambda item: (
            bool(item[1].quality.get("usable")),
            item[1].confidence,
            -float(item[1].quality.get("blur", 1.0)),
        ),
    )
    best_index, vision_result = _apply_burst_consensus(
        list(results),
        selected_index=best_index,
        red_digits=data.red_digits or 3,
        black_digits=data.black_digits or 4,
        previous_value=data.previous_value,
        hydrometer_brand=data.hydrometer_brand,
        hydrometer_model=data.hydrometer_model,
    )
    stable_visual_pair = _has_stable_visual_pair(
        list(results),
        red_digits=data.red_digits or 3,
        black_digits=data.black_digits or 4,
    )
    if len(frames) > 1 and not stable_visual_pair:
        missing_probe_indexes = [index for index in range(len(frames)) if index not in expensive_probe_indexes]
        if missing_probe_indexes:
            refreshed = await asyncio.gather(*[
                asyncio.to_thread(
                    meter_vision_service.analyze,
                    frames[index],
                    red_digits=data.red_digits,
                    black_digits=data.black_digits,
                    previous_value=data.previous_value,
                    expensive_ocr=True,
                    hydrometer_brand=data.hydrometer_brand,
                    hydrometer_model=data.hydrometer_model,
                    guide_crop=frame_guide_crops[index],
                )
                for index in missing_probe_indexes
            ])
            for index, result in zip(missing_probe_indexes, refreshed):
                results[index] = result
            best_index, vision_result = max(
                enumerate(results),
                key=lambda item: (
                    bool(item[1].quality.get("usable")),
                    item[1].confidence,
                    -float(item[1].quality.get("blur", 1.0)),
                ),
            )
            best_index, vision_result = _apply_burst_consensus(
                list(results),
                selected_index=best_index,
                red_digits=data.red_digits or 3,
                black_digits=data.black_digits or 4,
                previous_value=data.previous_value,
                hydrometer_brand=data.hydrometer_brand,
                hydrometer_model=data.hydrometer_model,
            )
    inference_id = uuid.uuid4()
    original_key = None
    rectified_key = None
    frame_keys: list[str] = []
    try:
        object_prefix = f"vision/{datetime.now(timezone.utc):%Y/%m/%d}/{inference_id}"
        decoded_frames = [decode_base64_upload(frame, "jpg") for frame in frames]
        frame_uploads = [
            asyncio.to_thread(
                save_binary,
                raw,
                f"{object_prefix}/frames/frame-{index:02d}.{ext}",
                content_type,
            )
            for index, (ext, raw, content_type) in enumerate(decoded_frames)
        ]
        frame_keys = list(await asyncio.gather(*frame_uploads))
        original_key = frame_keys[best_index]
        if vision_result.rectified_jpeg:
            rectified_key = await asyncio.to_thread(
                save_binary,
                vision_result.rectified_jpeg,
                f"{object_prefix}/rectified.jpg",
                "image/jpeg",
            )
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

    temporal_metadata = (vision_result.quality or {}).get("temporal_fusion") or {}
    decision_metadata = (vision_result.quality or {}).get("decision") or {}
    calibration_version = temporal_metadata.get("calibration_version") or decision_metadata.get("calibration_version")
    inference = VisionInference(
        id=inference_id,
        hydrometer_id=data.hydrometer_id,
        collaborator_id=user.id,
        stage=data.stage,
        original_object_key=original_key,
        rectified_object_key=rectified_key,
        frame_object_keys=frame_keys,
        capture_id=data.capture_id,
        capture_metadata={
            **(data.capture_metadata or {}),
            "frame_metadata": data.frame_metadata,
            "received_frames": len(frames),
            "selected_frame": best_index,
        },
        model_version=vision_result.model_version,
        predicted_code=vision_result.predicted_code,
        predicted_value=vision_result.predicted_value,
        confidence=vision_result.confidence,
        auto_fill_allowed=vision_result.auto_fill_allowed,
        decision=vision_result.decision,
        calibrated_confidence=vision_result.calibrated_confidence,
        decoder_version=vision_result.decoder_version,
        calibration_version=calibration_version,
        quality={**vision_result.quality, **({"glm_shadow": shadow} if shadow else {})},
        digits=vision_result.digits,
        alternatives=vision_result.alternatives,
        flags=vision_result.flags,
        red_digits=data.red_digits,
        black_digits=data.black_digits,
        hydrometer_brand=data.hydrometer_brand,
        hydrometer_model=data.hydrometer_model,
        dataset_version="aqua-meter-capture-v2",
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


@router.get("/vision-training/export")
async def export_vision_training_dataset(
    limit: int = 500,
    only_approved: bool = True,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Exporta amostras corrigidas para treino externo do detector/modelo OCR.

    Esse endpoint é o contrato do Sprint 1: cada confirmação humana vira linha
    de dataset com imagem original, crop retificado, leitura confirmada, leitura
    prevista, flags e métricas. YOLO/slot-model usam esse JSON para montar
    `images/` + `labels/` sem depender do banco em tempo de treino.
    """
    safe_limit = max(1, min(limit, 2000))
    query = (
        select(VisionInference)
        .where(VisionInference.confirmed_value.is_not(None))
        .order_by(VisionInference.created_at.desc())
        .limit(safe_limit)
    )
    if only_approved:
        query = query.where(VisionInference.approved_for_training.is_(True))
    result = await db.execute(query)
    items = result.scalars().all()

    samples = []
    for item in items:
        original_url = build_public_upload_url(item.original_object_key) if item.original_object_key else None
        rectified_url = build_public_upload_url(item.rectified_object_key) if item.rectified_object_key else None
        confirmed_code = item.confirmed_code
        if not confirmed_code and item.confirmed_value is not None:
            red_digits = item.red_digits if item.red_digits is not None else 3
            black_digits = item.black_digits if item.black_digits is not None else 4
            total_digits = max(3, min(red_digits + black_digits, 10))
            confirmed_code = str(int(round(float(item.confirmed_value) * (10 ** max(red_digits, 0))))).zfill(total_digits)
        predicted_code = None
        if item.predicted_value is not None:
            red_digits = item.red_digits if item.red_digits is not None else 3
            black_digits = item.black_digits if item.black_digits is not None else 4
            total_digits = max(3, min(red_digits + black_digits, 10))
            predicted_code = str(int(round(float(item.predicted_value) * (10 ** max(red_digits, 0))))).zfill(total_digits)
        samples.append({
            "id": str(item.id),
            "hydrometer_id": str(item.hydrometer_id) if item.hydrometer_id else None,
            "stage": item.stage,
            "created_at": item.created_at.isoformat(),
            "original_object_key": item.original_object_key,
            "rectified_object_key": item.rectified_object_key,
            "frame_object_keys": item.frame_object_keys or [],
            "original_url": original_url,
            "rectified_url": rectified_url,
            "confirmed_code": confirmed_code,
            "confirmed_value": item.confirmed_value,
            "predicted_code": predicted_code,
            "predicted_value": item.predicted_value,
            "was_correct": item.was_correct,
            "approved_for_training": item.approved_for_training,
            "dataset_source": (item.quality or {}).get("dataset_source", item.stage),
            "dataset_status": (item.quality or {}).get(
                "dataset_status",
                "approved_for_training" if item.approved_for_training else "diagnostic_confirmed",
            ),
            "confidence": item.confidence,
            "calibrated_confidence": item.calibrated_confidence,
            "decision": item.decision,
            "decoder_version": item.decoder_version,
            "calibration_version": item.calibration_version,
            "capture_metadata": item.capture_metadata or {},
            "red_digits": item.red_digits,
            "black_digits": item.black_digits,
            "brand": item.hydrometer_brand,
            "model": item.hydrometer_model,
            "quality": item.quality or {},
            "digits": item.digits or [],
            "slot_labels": item.slot_labels or [],
            "dataset_version": item.dataset_version,
            "alternatives": item.alternatives or [],
            "flags": item.flags or [],
        })
    return {
        "version": "aqua-meter-training-v2",
        "count": len(samples),
        "only_approved": only_approved,
        "samples": samples,
        "next_steps": [
            "Annotate counter_window OBB on original_url.",
            "Annotate 7 digit slots on rectified_url.",
            "Train detector and slot transition model.",
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
    hydrometer.customer = customer
    await ensure_actionable_cycle(db, hydrometer)
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
    _validate_manual_base_adjustment(hydrometer, update_data)
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
