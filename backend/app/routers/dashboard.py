"""
Router do Dashboard — KPIs e métricas para o painel admin.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import Customer
from app.models.reading import Reading
from app.models.invoice import Invoice
from app.models.user import User
from app.utils.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dados completos do dashboard."""
    now = datetime.now(timezone.utc)
    current_month = f"{now.year}-{now.month:02d}"

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
    invoices_result = await db.execute(
        select(
            func.coalesce(func.sum(case((Invoice.status == "pending", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.status == "overdue", Invoice.amount), else_=0)), 0),
            func.coalesce(func.sum(case(
                ((Invoice.status == "paid") & (Invoice.reference_month == current_month), Invoice.amount),
                else_=0,
            )), 0),
            func.sum(case((Invoice.status == "pending", 1), else_=0)),
            func.sum(case((Invoice.status == "overdue", 1), else_=0)),
            func.sum(case((Invoice.status == "paid", 1), else_=0)),
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
        select(func.count(Reading.id)).where(
            func.to_char(Reading.created_at, "YYYY-MM") == current_month
        )
    )
    month_readings = readings_month.scalar() or 0

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
                "total": 3100.0,
                "items": [
                    {"label": "Despesa operacional", "amount": 2000.0},
                    {"label": "Manutenção", "amount": 350.0},
                    {"label": "Energia", "amount": 600.0},
                    {"label": "Outros", "amount": 150.0},
                ],
            },
        },
        "readings": {
            "pending_approval": pending_readings,
            "this_month": month_readings,
        },
        "current_month": current_month,
    }
