"""Router de Hidrômetros - CRUD vinculado a clientes."""

import random
import re
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.user import User
from app.schemas.hydrometer import (
    HydrometerCreate,
    HydrometerIdentifyRequest,
    HydrometerIdentifyResponse,
    HydrometerListResponse,
    HydrometerResponse,
    HydrometerUpdate,
)
from app.services.kimi_vision import kimi_service
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/hydrometers", tags=["Hidrômetros"])


def normalize_hydrometer_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    return normalized or None


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
        raise HTTPException(status_code=404, detail="Hidrômetro não encontrado")
    return hydrometer


@router.post("/identify", response_model=HydrometerIdentifyResponse)
async def identify_hydrometer_from_photo(
    data: HydrometerIdentifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Extrai o código do hidrômetro pela foto e tenta associar ao cadastro."""
    ocr_result = await kimi_service.extract_hydrometer_data(data.photo_base64)
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


@router.post("", response_model=HydrometerResponse, status_code=201)
async def create_hydrometer(
    data: HydrometerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    customer_result = await db.execute(select(Customer).where(Customer.id == data.customer_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    target_code = normalize_hydrometer_code(data.code)
    if not target_code:
        target_code = "".join(random.choice(string.ascii_uppercase) for _ in range(6))

    existing = await db.execute(select(Hydrometer).where(Hydrometer.code == target_code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Este código já está em uso")

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
    result = await db.execute(
        select(Hydrometer).where(Hydrometer.id == uuid.UUID(hydrometer_id))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrômetro não encontrado")

    update_data = data.model_dump(exclude_unset=True)
    if "code" in update_data:
        update_data["code"] = normalize_hydrometer_code(update_data["code"])

    for field, value in update_data.items():
        setattr(hydrometer, field, value)

    await db.flush()
    await db.refresh(hydrometer)
    return hydrometer
