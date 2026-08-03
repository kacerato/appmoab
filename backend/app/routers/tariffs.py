"""Router de Tarifas — CRUD das faixas de tarifa."""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tariff import TariffTier
from app.models.user import User
from app.schemas.tariff import (
    TariffTierCreate, TariffTierUpdate, TariffTierResponse,
    TariffListResponse, BillingCalculation,
    MinimumChargeUpdate, MinimumChargeResponse,
)
from app.services.billing import calculate_billing
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/tariffs", tags=["Tarifas"])


@router.get("", response_model=TariffListResponse)
async def list_tariffs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TariffTier).order_by(TariffTier.sort_order)
    )
    items = result.scalars().all()
    return TariffListResponse(items=items, total=len(items))


@router.post("", response_model=TariffTierResponse, status_code=201)
async def create_tariff(
    data: TariffTierCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    tier = TariffTier(**data.model_dump())
    db.add(tier)
    await db.flush()
    await db.refresh(tier)
    return tier


@router.patch("/minimum-charge", response_model=MinimumChargeResponse)
async def update_minimum_charge(
    data: MinimumChargeUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Mantém uma única taxa mínima coerente em todas as faixas."""
    result = await db.execute(
        update(TariffTier)
        .values(minimum_charge=data.amount)
        .returning(TariffTier.id)
    )
    updated_tiers = len(result.all())
    if updated_tiers == 0:
        raise HTTPException(status_code=409, detail="Nenhuma faixa de tarifa configurada")
    await db.flush()
    return MinimumChargeResponse(amount=data.amount, updated_tiers=updated_tiers)


@router.patch("/{tier_id}", response_model=TariffTierResponse)
async def update_tariff(
    tier_id: str,
    data: TariffTierUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(TariffTier).where(TariffTier.id == uuid.UUID(tier_id))
    )
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Faixa não encontrada")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tier, field, value)

    await db.flush()
    await db.refresh(tier)
    return tier


@router.delete("/{tier_id}", status_code=204)
async def delete_tariff(
    tier_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(
        select(TariffTier).where(TariffTier.id == uuid.UUID(tier_id))
    )
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Faixa não encontrada")
    await db.delete(tier)


@router.get("/simulate/{consumption_m3}", response_model=BillingCalculation)
async def simulate_billing(
    consumption_m3: float,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Simula cálculo de fatura para um consumo dado."""
    return await calculate_billing(db, consumption_m3)
