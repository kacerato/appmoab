"""Router do Dashboard — KPIs e métricas para o painel admin."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.reading import Reading
from app.models.invoice import Invoice
from app.models.deduction import Deduction
from app.models.notification import Notification
from app.models.user import User
from app.utils.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _issue(
    *,
    code: str,
    title: str,
    detail: str,
    severity: str,
    href: str,
) -> dict:
    return {
        "code": code,
        "title": title,
        "detail": detail,
        "severity": severity,
        "href": href,
    }


async def _operational_issues(db: AsyncSession, limit: int = 12) -> list[dict]:
    issues: list[dict] = []

    approved_without_invoice = await db.execute(
        select(Reading.id, Customer.name, Hydrometer.code)
        .join(Hydrometer, Hydrometer.id == Reading.hydrometer_id)
        .join(Customer, Customer.id == Hydrometer.customer_id)
        .outerjoin(Invoice, Invoice.reading_id == Reading.id)
        .where(Reading.status == "approved", Invoice.id.is_(None))
        .order_by(Reading.approved_at.desc().nullslast(), Reading.created_at.desc())
        .limit(limit)
    )
    for reading_id, customer_name, hydrometer_code in approved_without_invoice.all():
        issues.append(_issue(
            code="approved_reading_without_invoice",
            title="Leitura aprovada sem fatura",
            detail=f"{customer_name} - hidrometro {hydrometer_code}",
            severity="danger",
            href=f"/leituras?reading_id={reading_id}",
        ))

    active_invoice_without_charge = await db.execute(
        select(Invoice.id, Customer.name, Invoice.reference_month, Invoice.status)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(
            Invoice.status.in_(("pending", "sent", "overdue")),
            Invoice.efi_charge_id.is_(None),
            Invoice.efi_payment_url.is_(None),
        )
        .order_by(Invoice.created_at.desc())
        .limit(limit)
    )
    for invoice_id, customer_name, reference_month, status in active_invoice_without_charge.all():
        issues.append(_issue(
            code="active_invoice_without_charge",
            title="Fatura ativa sem boleto/link",
            detail=f"{customer_name} - {reference_month} ({status})",
            severity="warning",
            href=f"/faturas/{invoice_id}",
        ))

    paid_without_date = await db.execute(
        select(Invoice.id, Customer.name, Invoice.reference_month)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.status == "paid", Invoice.paid_date.is_(None))
        .order_by(Invoice.updated_at.desc())
        .limit(limit)
    )
    for invoice_id, customer_name, reference_month in paid_without_date.all():
        issues.append(_issue(
            code="paid_invoice_without_date",
            title="Fatura paga sem data de pagamento",
            detail=f"{customer_name} - {reference_month}",
            severity="warning",
            href=f"/faturas/{invoice_id}",
        ))

    failed_invoice_notifications = await db.execute(
        select(Notification.invoice_id, Customer.name, Notification.error_message)
        .join(Customer, Customer.id == Notification.customer_id)
        .where(
            Notification.type == "invoice_generated",
            Notification.status == "failed",
            Notification.invoice_id.is_not(None),
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    for invoice_id, customer_name, error_message in failed_invoice_notifications.all():
        issues.append(_issue(
            code="invoice_whatsapp_failed",
            title="WhatsApp da fatura falhou",
            detail=f"{customer_name} - {(error_message or 'sem detalhe')[:120]}",
            severity="warning",
            href=f"/faturas/{invoice_id}",
        ))

    severity_order = {"danger": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda item: severity_order.get(item["severity"], 9))
    return issues[:limit]


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

    today = date.today()
    invoices_result = await db.execute(
        select(
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= today),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date > today),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (Invoice.status.in_(("pending", "sent", "overdue"))) & (Invoice.due_date < today),
                Invoice.amount,
            ), else_=0)), 0),
            func.coalesce(func.sum(case((paid_condition, Invoice.amount), else_=0)), 0),
            func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= today),
                1,
            ), else_=0)),
            func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date > today),
                1,
            ), else_=0)),
            func.sum(case((
                (Invoice.status.in_(("pending", "sent", "overdue"))) & (Invoice.due_date < today),
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
            "upcoming_amount": float(inv[1] or 0),
            "overdue_amount": float(inv[2] or 0),
            "paid_this_month": float(inv[3] or 0),
            "pending_count": int(inv[4] or 0),
            "upcoming_count": int(inv[5] or 0),
            "overdue_count": int(inv[6] or 0),
            "paid_count": int(inv[7] or 0),
            "deductions": {
                "total": deductions_total,
                "items": [{"label": d.label, "amount": d.amount} for d in deductions],
            },
        },
        "readings": {
            "pending_approval": pending_readings,
            "this_month": month_readings,
        },
        "operational_issues": await _operational_issues(db),
        "current_month": current_month,
        "scope": "all" if scope == "all" else "month",
    }
