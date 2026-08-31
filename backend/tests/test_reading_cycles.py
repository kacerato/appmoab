from datetime import date, datetime, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.reading_cycle import ReadingCycle
from app.models.reading import Reading
from app.routers.customers import _apply_billing_status
from app.schemas.customer import CustomerResponse
from app.services.reading_cycles import (
    cycle_timing,
    ensure_actionable_cycle,
    next_reference_month,
    register_administrative_baseline,
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


class InstallationCycleContractTest(IsolatedAsyncioTestCase):
    async def test_administrative_baseline_is_official_and_opens_next_water_cycle(self):
        customer = _customer()
        customer.has_hydrometer = False
        hydrometer = Hydrometer(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            customer_id=UUID("11111111-1111-1111-1111-111111111111"),
            code="000001",
        )
        hydrometer.customer = customer
        installation_cycle = _cycle()
        installation_cycle.id = UUID("33333333-3333-3333-3333-333333333333")
        installation_cycle.cycle_type = "installation"
        water_cycle = _cycle()
        water_cycle.reference_month = "2026-08"
        db = MagicMock()
        db.flush = AsyncMock()
        captured_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
        admin_id = UUID("44444444-4444-4444-4444-444444444444")

        with patch(
            "app.services.reading_cycles.create_cycle",
            AsyncMock(side_effect=[installation_cycle, water_cycle]),
        ) as create_cycle:
            reading = await register_administrative_baseline(
                db,
                hydrometer,
                value=90.645,
                captured_at=captured_at,
                admin_id=admin_id,
            )

        assert isinstance(reading, Reading)
        assert reading.status == "approved"
        assert reading.reading_kind == "installation"
        assert reading.consumption == 0
        assert reading.photo_url == ""
        assert installation_cycle.status == "completed"
        assert hydrometer.last_reading_value == 90.645
        assert hydrometer.last_reading_date == captured_at
        assert create_cycle.await_args_list[0].kwargs["cycle_type"] == "installation"
        assert create_cycle.await_args_list[0].kwargs["status"] == "completed"
        assert create_cycle.await_args_list[1].kwargs["reference"] == "2026-08"
        assert create_cycle.await_args_list[1].kwargs["cycle_type"] == "water"

    async def test_first_official_reading_is_installation_even_with_legacy_last_reading_date(self):
        hydrometer = Hydrometer(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            customer_id=UUID("11111111-1111-1111-1111-111111111111"),
            code="000001",
            last_reading_value=90.645,
            last_reading_date=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        expected = _cycle()
        expected.cycle_type = "installation"

        with (
            patch(
                "app.services.reading_cycles.get_actionable_cycle",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.reading_cycles.get_latest_approved_reading",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.reading_cycles.create_cycle",
                AsyncMock(return_value=expected),
            ) as create_cycle,
        ):
            result = await ensure_actionable_cycle(
                AsyncMock(),
                hydrometer,
                today=date(2026, 7, 27),
            )

        assert result.cycle_type == "installation"
        assert create_cycle.await_args.kwargs["cycle_type"] == "installation"

    async def test_legacy_water_cycle_is_promoted_when_no_reading_was_approved(self):
        hydrometer = Hydrometer(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            customer_id=UUID("11111111-1111-1111-1111-111111111111"),
            code="000001",
        )
        legacy_cycle = _cycle()
        promoted_cycle = _cycle()
        promoted_cycle.cycle_type = "installation"
        db = AsyncMock()

        with (
            patch(
                "app.services.reading_cycles.get_actionable_cycle",
                AsyncMock(return_value=legacy_cycle),
            ),
            patch(
                "app.services.reading_cycles.get_latest_approved_reading",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.reading_cycles.promote_cycle_to_installation",
                AsyncMock(return_value=promoted_cycle),
            ) as promote,
        ):
            result = await ensure_actionable_cycle(db, hydrometer)

        assert result.cycle_type == "installation"
        promote.assert_awaited_once_with(db, legacy_cycle)
