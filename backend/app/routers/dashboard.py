"""Router do Dashboard — KPIs e métricas para o painel admin."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import Customer
from app.models.reading import Reading
from app.models.invoice import Invoice
from app.models.deduction import Deduction
from app.models.user import User
from app.utils.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
async def get_dashboard(
    scope: str = "month",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dados completos do dashboard."""
    now = datetime.now(timezone.utc)
    current_month = f"{now.year}-{now.month:02d}"
    month_start = date(now.year, now.month, 1)
    if now.month == 12:
        next_month_start = date(now.year + 1, 1, 1)
    else:
        next_month_start = date(now.year, now.month + 1, 1)

    # Clientes
    customers_result = await db.execute(
        select(
            func.count(Customer.id),
            func.sum(case((Customer.status == "active", 1), else_=0)),
            func.sum(case((Customer.has_hydrometer == True, 1), else_=0)),  # noqa: E712
            func.sum(case((Customer.has_hydrometer == False, 1), else_=0)),  # noqa: E712
        )
    )
    c = customers_result.one()

    # Faturas
    paid_condition = Invoice.status == "paid"
    readings_condition = True
    if scope != "all":
        paid_condition = paid_condition & (Invoice.paid_date >= month_start) & (Invoice.paid_date < next_month_start)
        readings_condition = func.to_char(Reading.created_at, "YYYY-MM") == current_month

    invoices_result = await db.execute(
        select(
            func.coalesce(func.sum(case((Invoice.status == "pending", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(case((
                (Invoice.status.in_(("pending", "sent", "overdue"))) & (Invoice.due_date < date.today()),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((paid_condition, Invoice.amount), else_=0)), 0),
            func.sum(case((Invoice.status == "pending", 1), else_=0)),
            func.sum(case((
                (Invoice.status.in_(("pending", "sent", "overdue"))) & (Invoice.due_date < date.today()),
                1,
            ), else_=0)),
            func.sum(case((paid_condition, 1), else_=0)),
        )
    )
    inv = invoices_result.one()

    # Leituras pendentes
    readings_pending = await db.execute(
        select(func.count(Reading.id)).where(Reading.status == "pending")
    )
    pending_readings = readings_pending.scalar() or 0

    # Leituras do mês
    readings_month = await db.execute(
        select(func.count(Reading.id)).where(readings_condition)
    )
    month_readings = readings_month.scalar() or 0

    # Deduções do banco de dados
    deductions_result = await db.execute(
        select(Deduction).where(Deduction.is_active == True).order_by(Deduction.sort_order)  # noqa: E712
    )
    deductions = deductions_result.scalars().all()
    deductions_total = sum(d.amount for d in deductions)

    return {
        "customers": {
            "total": c[0] or 0,
            "active": int(c[1] or 0),
            "with_hydrometer": int(c[2] or 0),
            "without_hydrometer": int(c[3] or 0),
        },
        "financial": {
            "pending_amount": float(inv[0] or 0),
            "overdue_amount": float(inv[1] or 0),
            "paid_this_month": float(inv[2] or 0),
            "pending_count": int(inv[3] or 0),
            "overdue_count": int(inv[4] or 0),
            "paid_count": int(inv[5] or 0),
            "deductions": {
                "total": deductions_total,
                "items": [{"label": d.label, "amount": d.amount} for d in deductions],
            },
        },
        "readings": {
            "pending_approval": pending_readings,
            "this_month": month_readings,
        },
        "current_month": current_month,
        "scope": "all" if scope == "all" else "month",
    }
