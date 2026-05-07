"""Router de Hidrômetros — CRUD vinculado a clientes."""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.hydrometer import Hydrometer
from app.models.user import User
from app.schemas.hydrometer import (
    HydrometerCreate, HydrometerUpdate, HydrometerResponse, HydrometerListResponse,
)
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/hydrometers", tags=["Hidrômetros"])


@router.get("", response_model=HydrometerListResponse)
async def list_hydrometers(
    customer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Hydrometer)
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
        select(Hydrometer).where(Hydrometer.id == uuid.UUID(hydrometer_id))
    )
    hydrometer = result.scalar_one_or_none()
    if not hydrometer:
        raise HTTPException(status_code=404, detail="Hidrômetro não encontrado")
    return hydrometer


@router.post("", response_model=HydrometerResponse, status_code=201)
async def create_hydrometer(
    data: HydrometerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = await db.execute(select(Hydrometer).where(Hydrometer.code == data.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Código de hidrômetro já cadastrado")

    hydrometer = Hydrometer(
        customer_id=data.customer_id,
        code=data.code,
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

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(hydrometer, field, value)

    await db.flush()
    await db.refresh(hydrometer)
    return hydrometer
