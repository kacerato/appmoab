"""Router de Deduções — CRUD de despesas mensais configuráveis."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.deduction import Deduction
from app.models.user import User
from app.schemas.deduction import (
    DeductionCreate, DeductionUpdate, DeductionResponse, DeductionListResponse,
)
from app.utils.security import require_admin

router = APIRouter(prefix="/deductions", tags=["Deduções"])


@router.get("", response_model=DeductionListResponse)
async def list_deductions(db: AsyncSession = Depends(get_db)):
    """Lista todas as deduções ativas."""
    result = await db.execute(
        select(Deduction).where(Deduction.is_active == True).order_by(Deduction.sort_order)  # noqa: E712
    )
    items = result.scalars().all()
    total = sum(d.amount for d in items)
    return DeductionListResponse(items=items, total=total)


@router.post("", response_model=DeductionResponse, status_code=201)
async def create_deduction(
    data: DeductionCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Cria uma nova dedução (apenas admin)."""
    deduction = Deduction(**data.model_dump())
    db.add(deduction)
    await db.flush()
    await db.refresh(deduction)
    return deduction


@router.patch("/{deduction_id}", response_model=DeductionResponse)
async def update_deduction(
    deduction_id: str,
    data: DeductionUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Atualiza uma dedução (apenas admin)."""
    result = await db.execute(
        select(Deduction).where(Deduction.id == uuid.UUID(deduction_id))
    )
    deduction = result.scalar_one_or_none()
    if not deduction:
        raise HTTPException(status_code=404, detail="Dedução não encontrada")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(deduction, field, value)

    await db.flush()
    await db.refresh(deduction)
    return deduction


@router.delete("/{deduction_id}", status_code=204)
async def delete_deduction(
    deduction_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Remove uma dedução (apenas admin)."""
    result = await db.execute(
        select(Deduction).where(Deduction.id == uuid.UUID(deduction_id))
    )
    deduction = result.scalar_one_or_none()
    if not deduction:
        raise HTTPException(status_code=404, detail="Dedução não encontrada")
    await db.delete(deduction)
