"""
Router de Clientes — CRUD completo com filtros e paginação.
"""

import uuid
import random
import string
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate, CustomerUpdate, CustomerResponse,
    CustomerDetailResponse, CustomerListResponse,
)
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/customers", tags=["Clientes"])


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=2000),
    search: str | None = None,
    status: str | None = None,
    has_hydrometer: bool | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lista clientes com filtros e paginação."""
    query = select(Customer).options(selectinload(Customer.hydrometers))

    if search:
        query = query.where(
            or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.cpf_cnpj.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
            )
        )
    if status:
        query = query.where(Customer.status == status)
    if has_hydrometer is not None:
        query = query.where(Customer.has_hydrometer == has_hydrometer)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    offset = (page - 1) * per_page
    query = query.order_by(Customer.name).offset(offset).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    return CustomerListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{customer_id}", response_model=CustomerDetailResponse)
async def get_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Detalhe completo do cliente com hidrômetros e resumo financeiro."""
    result = await db.execute(
        select(Customer)
        .options(selectinload(Customer.hydrometers))
        .where(Customer.id == uuid.UUID(customer_id))
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Resumo financeiro
    inv_result = await db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(
                case((Invoice.status == "pending", Invoice.amount), else_=0)
            ), 0),
            func.coalesce(func.sum(
                case((Invoice.status == "overdue", Invoice.amount), else_=0)
            ), 0),
        ).where(Invoice.customer_id == customer.id)
    )
    total_inv, pending, overdue = inv_result.one()

    response = CustomerDetailResponse.model_validate(customer)
    response.total_invoices = total_inv
    response.total_pending = float(pending)
    response.total_overdue = float(overdue)
    return response


@router.post("", response_model=CustomerResponse, status_code=201)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Cadastro de novo cliente."""
    existing = await db.execute(
        select(Customer).where(Customer.cpf_cnpj == data.cpf_cnpj)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="CPF/CNPJ já cadastrado")

    customer = Customer(**data.model_dump())
    db.add(customer)
    await db.flush()

    if customer.has_hydrometer:
        from app.models.hydrometer import Hydrometer
        
        # Gera código aleatório de 6 letras para identificação mais fácil (ex: ABXCJY)
        def generate_short_code():
            return ''.join(random.choice(string.ascii_uppercase) for _ in range(6))
            
        hydrometer = Hydrometer(
            customer_id=customer.id,
            code=generate_short_code(),
            location_description="Instalação Padrão",
            last_reading_value=0.0,
        )
        db.add(hydrometer)
        await db.flush()

    await db.refresh(customer)
    return customer


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Atualiza dados do cliente."""
    result = await db.execute(
        select(Customer).where(Customer.id == uuid.UUID(customer_id))
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)

    await db.flush()
    await db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Remove um cliente (soft-delete via status)."""
    result = await db.execute(
        select(Customer).where(Customer.id == uuid.UUID(customer_id))
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    await db.delete(customer)
    await db.flush()
