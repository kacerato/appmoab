"""Router de hidrometros - CRUD vinculado a clientes."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.kimi_memory import KimiVisionMemory
from app.models.user import User
from app.schemas.hydrometer import (
    HydrometerCreate,
    HydrometerIdentifyRequest,
    HydrometerIdentifyResponse,
    HydrometerListResponse,
    HydrometerResponse,
    HydrometerResolveCodeRequest,
    KimiVisionFeedbackRequest,
    HydrometerUpdate,
)
from app.services.hydrometer_codes import assign_numeric_code_if_needed, normalize_hydrometer_code
from app.services.kimi_vision import KimiVisionError, kimi_service
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/hydrometers", tags=["Hidrometros"])


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
        ocr_result = await kimi_service.extract_hydrometer_data(data.photo_base64)
    except KimiVisionError as exc:
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
        customer_id=hydrometer.customer_id,
        customer_name=hydrometer.customer.name if hydrometer.customer else None,
        location_description=hydrometer.location_description,
        last_reading_value=hydrometer.last_reading_value,
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
        customer_id=hydrometer.customer_id,
        customer_name=hydrometer.customer.name if hydrometer.customer else None,
        location_description=hydrometer.location_description,
        last_reading_value=hydrometer.last_reading_value,
    )


@router.post("/vision-feedback")
async def store_kimi_vision_feedback(
    data: KimiVisionFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Registra o veredito interno do Kimi contra o valor digitado pelo colaborador."""
    predicted_code = normalize_hydrometer_code(data.predicted_code)
    confirmed_code = normalize_hydrometer_code(data.confirmed_code)
    was_correct = None
    if data.stage == "code" and confirmed_code:
        was_correct = predicted_code == confirmed_code
    elif data.stage == "reading" and data.confirmed_value is not None and data.predicted_value is not None:
        was_correct = abs(float(data.confirmed_value) - float(data.predicted_value)) <= 0.01

    lesson = "Aguardando confirmacao humana."
    if was_correct is True:
        lesson = "Veredito conferiu com a digitacao do colaborador."
    elif was_correct is False:
        lesson = (
            "Divergencia registrada: revisar foco, recorte, reflexo, sujeira ou digitos parecidos "
            "nas proximas leituras."
        )

    memory = KimiVisionMemory(
        hydrometer_id=data.hydrometer_id,
        collaborator_id=user.id,
        stage=data.stage,
        predicted_code=predicted_code,
        predicted_value=data.predicted_value,
        confirmed_code=confirmed_code,
        confirmed_value=data.confirmed_value,
        confidence=data.confidence,
        was_correct=was_correct,
        lesson=lesson,
        payload={"has_photo": bool(data.photo_base64)},
    )
    db.add(memory)
    await db.flush()
    return {"id": str(memory.id), "was_correct": was_correct, "lesson": lesson}


@router.post("/vision-verdict")
async def kimi_vision_verdict(
    data: HydrometerIdentifyRequest,
    user: User = Depends(get_current_user),
):
    """Executa o Kimi nos bastidores. O app nao bloqueia o colaborador neste retorno."""
    try:
        ocr_result = await kimi_service.extract_hydrometer_data(data.photo_base64)
        return {
            "predicted_code": normalize_hydrometer_code(ocr_result.get("codigo")),
            "predicted_value": ocr_result.get("leitura_m3"),
            "confidence": ocr_result.get("confianca"),
        }
    except KimiVisionError as exc:
        return {"predicted_code": None, "predicted_value": None, "confidence": 0.0, "error": str(exc)}


@router.get("/kimi-memory/summary")
async def kimi_memory_summary(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    total = (await db.execute(select(func.count()).select_from(KimiVisionMemory))).scalar() or 0
    correct = (
        await db.execute(
            select(func.count()).select_from(KimiVisionMemory).where(KimiVisionMemory.was_correct.is_(True))
        )
    ).scalar() or 0
    wrong = (
        await db.execute(
            select(func.count()).select_from(KimiVisionMemory).where(KimiVisionMemory.was_correct.is_(False))
        )
    ).scalar() or 0
    recent_result = await db.execute(
        select(KimiVisionMemory).order_by(KimiVisionMemory.created_at.desc()).limit(8)
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
                "was_correct": item.was_correct,
                "lesson": item.lesson,
                "created_at": item.created_at,
            }
            for item in recent
        ],
    }


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

    hydrometer = Hydrometer(
        customer_id=data.customer_id,
        code=target_code,
        brand=data.brand,
        model=data.model,
        location_description=data.location_description,
        latitude=data.latitude,
        longitude=data.longitude,
        last_reading_value=data.initial_reading,
    )
    db.add(hydrometer)
    await db.flush()
    await db.refresh(hydrometer)
    return hydrometer


@router.patch("/{hydrometer_id}", response_model=HydrometerResponse)
async def update_hydrometer(
    hydrometer_id: str,
    data: HydrometerUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Hydrometer).where(Hydrometer.id == uuid.UUID(hydrometer_id)))
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
    if "last_reading_value" in update_data and update_data["last_reading_value"] is not None:
        hydrometer.last_reading_date = datetime.now(timezone.utc)

    for field, value in update_data.items():
        setattr(hydrometer, field, value)

    await db.flush()
    await db.refresh(hydrometer)
    return hydrometer
