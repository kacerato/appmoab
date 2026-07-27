from datetime import date, datetime, timezone

from app.models.customer import Customer
from app.models.reading_cycle import ReadingCycle
from app.routers.customers import _apply_billing_status
from app.schemas.customer import CustomerResponse
from app.services.reading_cycles import (
    cycle_timing,
    next_reference_month,
    reference_due_date,
)


def _customer() -> Customer:
    return Customer(
        id="11111111-1111-1111-1111-111111111111",
        name="Cliente",
        cpf_cnpj="12345678909",
        address="Rua A",
        number="S/N",
        neighborhood="Centro",
        city="Petrolina",
        state="PE",
        zip_code="56300000",
        due_day=18,
        has_hydrometer=True,
        status="active",
        created_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        hydrometers=[],
    )


def _cycle(*, status: str = "open") -> ReadingCycle:
    return ReadingCycle(
        customer_id="11111111-1111-1111-1111-111111111111",
        hydrometer_id="22222222-2222-2222-2222-222222222222",
        reference_month="2026-07",
        due_date=date(2026, 7, 18),
        cycle_type="water",
        status=status,
    )


def test_reference_advance_keeps_missing_july_instead_of_skipping_to_august():
    assert next_reference_month("2026-06") == "2026-07"
    assert reference_due_date("2026-07", 18) == date(2026, 7, 18)


def test_overdue_cycle_never_disappears_after_route_window():
    state, days = cycle_timing(_cycle(), date(2026, 7, 27), days_before=2, grace_days=1)

    assert state == "late"
    assert days == 9


def test_rejected_cycle_returns_as_required_recapture():
    state, _ = cycle_timing(
        _cycle(status="recapture_required"),
        date(2026, 7, 27),
        days_before=2,
        grace_days=1,
    )

    assert state == "recapture_required"


def test_customer_status_reports_missing_reading_not_next_month_invoice():
    customer = _customer()
    response = CustomerResponse.model_validate(customer)

    _apply_billing_status(
        response,
        customer,
        date(2026, 7, 27),
        active_cycle=_cycle(),
    )

    assert response.billing_status == "reading_overdue"
    assert response.next_invoice_reference_month == "2026-07"
    assert response.next_invoice_due_date.date() == date(2026, 7, 18)
    assert "fatura ainda nao gerada" in response.billing_status_label
