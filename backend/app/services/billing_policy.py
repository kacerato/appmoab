"""Regras centrais de vencimento, atraso e emissao de cobranca."""

from dataclasses import dataclass
from datetime import date


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
    """A API de cobranca nao deve receber vencimento anterior ao dia da emissao."""
    return max(invoice_due_date, today)


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
