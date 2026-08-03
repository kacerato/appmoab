"""Regras centrais de vencimento, atraso e emissao de cobranca."""

from dataclasses import dataclass
from datetime import date
from calendar import monthrange


@dataclass(frozen=True)
class OverdueCalculation:
    base_amount: float
    late_fee_amount: float
    interest_amount: float
    days_overdue_charged: int
    total_amount: float
    is_overdue: bool


def resolve_invoice_due_date(reference: date, due_day: int) -> date:
    """Mantem a competencia no mes de referencia, mesmo apos o dia de vencimento."""
    if not 1 <= due_day <= 28:
        raise ValueError("Dia de vencimento deve ficar entre 1 e 28")
    return date(reference.year, reference.month, due_day)


def payment_due_date_for_provider(invoice_due_date: date, today: date) -> date:
    """Preserva o dia de vencimento no próximo mês válido para a cobrança."""
    if invoice_due_date >= today:
        return invoice_due_date

    due_day = invoice_due_date.day
    current_month_due = date(
        today.year,
        today.month,
        min(due_day, monthrange(today.year, today.month)[1]),
    )
    if current_month_due >= today:
        return current_month_due

    next_year = today.year + (1 if today.month == 12 else 0)
    next_month = 1 if today.month == 12 else today.month + 1
    return date(next_year, next_month, min(due_day, monthrange(next_year, next_month)[1]))


def should_block_overdue_charges_for_late_reading(
    *,
    charge_type: str,
    invoice_due_date: date,
    created_on: date,
) -> bool:
    return charge_type == "water" and created_on > invoice_due_date


def calculate_overdue_amount(
    *,
    original_amount: float,
    custom_adjustment_amount: float,
    due_date: date,
    today: date,
    late_fee_percent: float,
    daily_interest_percent: float,
    requested_days_overdue: int | None = None,
    overdue_charges_allowed: bool = True,
) -> OverdueCalculation:
    days = max(0, requested_days_overdue if requested_days_overdue is not None else (today - due_date).days)
    base_with_adjustment = round(original_amount + custom_adjustment_amount, 2)
    if days <= 0 or not overdue_charges_allowed:
        return OverdueCalculation(
            base_amount=original_amount,
            late_fee_amount=0.0,
            interest_amount=0.0,
            days_overdue_charged=0 if not overdue_charges_allowed else days,
            total_amount=base_with_adjustment,
            is_overdue=today > due_date,
        )

    late_fee = round(original_amount * (late_fee_percent / 100), 2)
    interest = round(original_amount * (daily_interest_percent / 100) * days, 2)
    return OverdueCalculation(
        base_amount=original_amount,
        late_fee_amount=late_fee,
        interest_amount=interest,
        days_overdue_charged=days,
        total_amount=round(base_with_adjustment + late_fee + interest, 2),
        is_overdue=True,
    )
