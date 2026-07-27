"""Router do Dashboard — KPIs e métricas para o painel admin."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import String, case, cast, func, literal, select, true, union_all
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
from app.utils.storage import HISTORICAL_IMPORT_PHOTO_PREFIX

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _issue(
    *,
    code: str,
    title: str,
    detail: str,
    severity: str,
    href: str,
) -> dict:
    """Mantém o formato público dos alertas e serve aos testes de contrato."""
    return {
        "code": code,
        "title": title,
        "detail": detail,
        "severity": severity,
        "href": href,
    }


async def _operational_issues(db: AsyncSession, limit: int = 12) -> list[dict]:
    approved_without_invoice = (
        select(Reading.id, Customer.name, Hydrometer.code)
        .join(Hydrometer, Hydrometer.id == Reading.hydrometer_id)
        .join(Customer, Customer.id == Hydrometer.customer_id)
        .outerjoin(Invoice, Invoice.reading_id == Reading.id)
        .where(
            Reading.status == "approved",
            Invoice.id.is_(None),
            Reading.photo_url.not_like(f"{HISTORICAL_IMPORT_PHOTO_PREFIX}%"),
        )
        .with_only_columns(
            literal("approved_reading_without_invoice").label("code"),
            literal("Leitura aprovada sem fatura").label("title"),
            func.concat(Customer.name, " - hidrometro ", Hydrometer.code).label("detail"),
            literal("danger").label("severity"),
            func.concat("/leituras?reading_id=", cast(Reading.id, String)).label("href"),
            func.coalesce(Reading.approved_at, Reading.created_at).label("event_at"),
            literal(0).label("severity_rank"),
        )
    )
    active_invoice_without_charge = (
        select(Invoice.id, Customer.name, Invoice.reference_month, Invoice.status)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(
            Invoice.status.in_(("pending", "sent", "overdue")),
            Invoice.efi_charge_id.is_(None),
            Invoice.efi_payment_url.is_(None),
        )
        .with_only_columns(
            literal("active_invoice_without_charge").label("code"),
            literal("Fatura ativa sem boleto/link").label("title"),
            func.concat(
                Customer.name, " - ", Invoice.reference_month, " (", Invoice.status, ")"
            ).label("detail"),
            literal("warning").label("severity"),
            func.concat("/faturas/", cast(Invoice.id, String)).label("href"),
            Invoice.created_at.label("event_at"),
            literal(1).label("severity_rank"),
        )
    )
    paid_without_date = (
        select(Invoice.id, Customer.name, Invoice.reference_month)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.status == "paid", Invoice.paid_date.is_(None))
        .with_only_columns(
            literal("paid_invoice_without_date").label("code"),
            literal("Fatura paga sem data de pagamento").label("title"),
            func.concat(Customer.name, " - ", Invoice.reference_month).label("detail"),
            literal("warning").label("severity"),
            func.concat("/faturas/", cast(Invoice.id, String)).label("href"),
            Invoice.updated_at.label("event_at"),
            literal(1).label("severity_rank"),
        )
    )
    failed_invoice_notifications = (
        select(Notification.invoice_id, Customer.name, Notification.error_message)
        .join(Customer, Customer.id == Notification.customer_id)
        .where(
            Notification.type == "invoice_generated",
            Notification.status == "failed",
            Notification.invoice_id.is_not(None),
        )
        .with_only_columns(
            literal("invoice_whatsapp_failed").label("code"),
            literal("WhatsApp da fatura falhou").label("title"),
            func.concat(
                Customer.name,
                " - ",
                func.left(func.coalesce(Notification.error_message, "sem detalhe"), 120),
            ).label("detail"),
            literal("warning").label("severity"),
            func.concat("/faturas/", cast(Notification.invoice_id, String)).label("href"),
            Notification.created_at.label("event_at"),
            literal(1).label("severity_rank"),
        )
    )

    combined = union_all(
        approved_without_invoice,
        active_invoice_without_charge,
        paid_without_date,
        failed_invoice_notifications,
    ).subquery()
    result = await db.execute(
        select(
            combined.c.code,
            combined.c.title,
            combined.c.detail,
            combined.c.severity,
            combined.c.href,
        )
        .order_by(combined.c.severity_rank, combined.c.event_at.desc())
        .limit(limit)
    )
    return [dict(row) for row in result.mappings().all()]


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

    # As métricas principais são subconsultas de uma única instrução SQL. No
    # banco remoto, isso remove quatro viagens de rede da primeira abertura do
    # painel sem alterar o contrato retornado ao frontend.
    customer_metrics = (
        select(
            func.count(Customer.id).label("total"),
            func.sum(case((Customer.status == "active", 1), else_=0)).label("active"),
            func.sum(case((Customer.has_hydrometer == True, 1), else_=0)).label("with_hydrometer"),  # noqa: E712
            func.sum(case((Customer.has_hydrometer == False, 1), else_=0)).label("without_hydrometer"),  # noqa: E712
        )
        .subquery()
    )

    # Faturas
    paid_condition = Invoice.status == "paid"
    readings_condition = True
    if scope != "all":
        paid_condition = paid_condition & (Invoice.paid_date >= month_start) & (Invoice.paid_date < next_month_start)
        readings_condition = func.to_char(Reading.created_at, "YYYY-MM") == current_month

    today = date.today()
    invoice_metrics = (
        select(
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= today),
                Invoice.amount,
            ), else_=0)), 0).label("pending_amount"),
            func.coalesce(func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date > today),
                Invoice.amount,
            ), else_=0)), 0).label("upcoming_amount"),
            func.coalesce(func.sum(case((
                (Invoice.status.in_(("pending", "sent", "overdue"))) & (Invoice.due_date < today),
                Invoice.amount,
            ), else_=0)), 0).label("overdue_amount"),
            func.coalesce(func.sum(case((paid_condition, Invoice.amount), else_=0)), 0).label("paid_amount"),
            func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date <= today),
                1,
            ), else_=0)).label("pending_count"),
            func.sum(case((
                (Invoice.status == "pending") & (Invoice.due_date > today),
                1,
            ), else_=0)).label("upcoming_count"),
            func.sum(case((
                (Invoice.status.in_(("pending", "sent", "overdue"))) & (Invoice.due_date < today),
                1,
            ), else_=0)).label("overdue_count"),
            func.sum(case((paid_condition, 1), else_=0)).label("paid_count"),
        )
        .subquery()
    )
    reading_metrics = (
        select(
            func.sum(case((Reading.status == "pending", 1), else_=0)).label("pending"),
            func.sum(case((readings_condition, 1), else_=0)).label("month"),
        )
        .subquery()
    )

    metrics_result = await db.execute(
        select(customer_metrics, invoice_metrics, reading_metrics)
        .select_from(
            customer_metrics
            .join(invoice_metrics, true())
            .join(reading_metrics, true())
        )
    )
    metrics = metrics_result.mappings().one()

    # Deduções do banco de dados
    deductions_result = await db.execute(
        select(Deduction).where(Deduction.is_active == True).order_by(Deduction.sort_order)  # noqa: E712
    )
    deductions = deductions_result.scalars().all()
    deductions_total = sum(d.amount for d in deductions)

    return {
        "customers": {
            "total": metrics["total"] or 0,
            "active": int(metrics["active"] or 0),
            "with_hydrometer": int(metrics["with_hydrometer"] or 0),
            "without_hydrometer": int(metrics["without_hydrometer"] or 0),
        },
        "financial": {
            "pending_amount": float(metrics["pending_amount"] or 0),
            "upcoming_amount": float(metrics["upcoming_amount"] or 0),
            "overdue_amount": float(metrics["overdue_amount"] or 0),
            "paid_this_month": float(metrics["paid_amount"] or 0),
            "pending_count": int(metrics["pending_count"] or 0),
            "upcoming_count": int(metrics["upcoming_count"] or 0),
            "overdue_count": int(metrics["overdue_count"] or 0),
            "paid_count": int(metrics["paid_count"] or 0),
            "deductions": {
                "total": deductions_total,
                "items": [{"label": d.label, "amount": d.amount} for d in deductions],
            },
        },
        "readings": {
            "pending_approval": int(metrics["pending"] or 0),
            "this_month": int(metrics["month"] or 0),
        },
        "operational_issues": await _operational_issues(db),
        "current_month": current_month,
        "scope": "all" if scope == "all" else "month",
    }
