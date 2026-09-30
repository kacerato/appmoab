from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.customer import Customer
from app.models.reading_cycle import ReadingCycle
from app.models.system_setting import SystemSetting
from app.routers.customers import (
    BulkDueDayUpdate,
    _customer_in_route_window,
    _next_due_date,
    update_all_customers_due_day,
    update_customer,
)
from app.schemas.customer import CustomerCreate, CustomerUpdate
from app.schemas.system_setting import SystemSettingUpdate
from app.services.billing_policy import resolve_invoice_due_date
from app.services.reading_cycles import cycle_timing, reference_due_date


def customer_payload(due_day: int) -> dict:
    return dict(
        name="Cliente fim do mes", cpf_cnpj="12345678909", address="Rua A",
        neighborhood="Centro", city="Petrolina", state="PE", zip_code="56300000",
        due_day=due_day,
    )


@pytest.mark.parametrize("due_day", [1, 28, 29, 30, 31])
def test_customer_and_settings_accept_month_end_due_days(due_day):
    assert CustomerCreate(**customer_payload(due_day)).due_day == due_day
    assert CustomerUpdate(due_day=due_day).due_day == due_day
    assert BulkDueDayUpdate(due_day=due_day).due_day == due_day
    settings = SystemSettingUpdate(
        route_window_enabled=True, route_window_days_before_due=2,
        route_window_days_after_due=1, default_due_day=due_day,
    )
    assert settings.default_due_day == due_day


@pytest.mark.parametrize("due_day", [0, 32, -1])
def test_customer_and_settings_reject_days_outside_calendar(due_day):
    factories = [
        lambda: CustomerCreate(**customer_payload(due_day)),
        lambda: CustomerUpdate(due_day=due_day),
        lambda: BulkDueDayUpdate(due_day=due_day),
        lambda: SystemSettingUpdate(
            route_window_enabled=True, route_window_days_before_due=2,
            route_window_days_after_due=1, default_due_day=due_day,
        ),
    ]
    for factory in factories:
        with pytest.raises(ValidationError):
            factory()
    with pytest.raises(ValueError):
        resolve_invoice_due_date(date(2026, 9, 1), due_day)


@pytest.mark.parametrize("due_day", [29, 30, 31])
@pytest.mark.parametrize("year,last_day", [(2026, 28), (2028, 29)])
def test_invoice_and_reading_cycle_keep_february_reference(due_day, year, last_day):
    expected = date(year, 2, last_day)
    assert resolve_invoice_due_date(date(year, 2, 1), due_day) == expected
    assert reference_due_date(f"{year}-02", due_day) == expected


def test_day_31_returns_after_short_month_without_changing_customer_day():
    customer = Customer(due_day=31, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert _next_due_date(customer, date(2026, 9, 29)) == date(2026, 9, 30)
    assert _next_due_date(customer, date(2026, 10, 1)) == date(2026, 10, 31)
    assert customer.due_day == 31


def test_new_customer_next_month_handles_february_and_december_rollover():
    customer = Customer(due_day=31, created_at=datetime(2026, 1, 15, tzinfo=timezone.utc))
    assert _next_due_date(customer, date(2026, 1, 15)) == date(2026, 2, 28)
    customer.created_at = datetime(2026, 12, 15, tzinfo=timezone.utc)
    assert _next_due_date(customer, date(2026, 12, 15)) == date(2027, 1, 31)


def test_route_opens_two_days_before_february_end_and_keeps_overdue_task():
    customer = Customer(due_day=31, hydrometers=[])
    settings = SystemSetting(
        route_window_enabled=True, route_window_days_before_due=2,
        route_window_days_after_due=1,
    )
    assert not _customer_in_route_window(customer, settings, date(2026, 2, 25))
    assert _customer_in_route_window(customer, settings, date(2026, 2, 26))
    assert _customer_in_route_window(customer, settings, date(2026, 3, 1))
    cycle = ReadingCycle(
        due_date=reference_due_date("2026-02", 31), cycle_type="water", status="open",
    )
    assert cycle_timing(cycle, date(2026, 3, 2), 2, 1) == ("late", 2)


@pytest.mark.asyncio
async def test_editing_customer_updates_open_cycles_for_each_month():
    customer = Customer(id=uuid4(), due_day=10)
    cycles = [ReadingCycle(reference_month=month) for month in ("2026-02", "2026-03")]
    customer_result, cycles_result = MagicMock(), MagicMock()
    customer_result.scalar_one_or_none.return_value = customer
    cycles_result.scalars.return_value.all.return_value = cycles
    db = AsyncMock()
    db.execute.side_effect = [customer_result, cycles_result]

    result = await update_customer(str(customer.id), CustomerUpdate(due_day=31), db, MagicMock())

    assert result.due_day == 31
    assert [cycle.due_date for cycle in cycles] == [date(2026, 2, 28), date(2026, 3, 31)]


@pytest.mark.asyncio
async def test_bulk_due_day_updates_short_and_long_month_cycles():
    customer_id = uuid4()
    cycles = [ReadingCycle(reference_month=month) for month in ("2028-02", "2028-03")]
    update_result, cycles_result = MagicMock(), MagicMock()
    update_result.scalars.return_value.all.return_value = [customer_id]
    cycles_result.scalars.return_value.all.return_value = cycles
    db = AsyncMock()
    db.execute.side_effect = [update_result, cycles_result]

    result = await update_all_customers_due_day(BulkDueDayUpdate(due_day=31), db, MagicMock())

    assert result == {"updated": 1, "due_day": 31}
    assert [cycle.due_date for cycle in cycles] == [date(2028, 2, 29), date(2028, 3, 31)]


@pytest.mark.asyncio
async def test_fixed_invoice_generation_accepts_day_31_in_february():
    from app.tasks.check_payments import _generate_fixed_async

    customer = Customer(id=uuid4(), **customer_payload(31))
    settings = SystemSetting(
        auto_send_invoice_on_approval=False, late_fee_percent=10, daily_interest_percent=0.033,
    )
    customers_result, settings_result, existing_result = MagicMock(), MagicMock(), MagicMock()
    customers_result.scalars.return_value.all.return_value = [customer]
    settings_result.scalar_one_or_none.return_value = settings
    existing_result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [customers_result, settings_result, existing_result]
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("app.database.async_session_factory", session),
        patch("app.tasks.check_payments.datetime") as clock,
        patch("app.tasks.check_payments.date") as day,
        patch("app.services.billing.get_fixed_rate", AsyncMock(return_value=100)),
        patch("app.services.efi_api.efi_service.emitir_cobranca", AsyncMock(return_value={})) as emit,
    ):
        clock.now.return_value = datetime(2026, 2, 27, tzinfo=timezone.utc)
        day.today.return_value = date(2026, 2, 27)
        await _generate_fixed_async()

    invoice = db.add.call_args.args[0]
    assert invoice.due_date == date(2026, 2, 28)
    assert invoice.reference_month == "2026-02"
    assert emit.call_args.kwargs["data_vencimento"] == date(2026, 2, 28)
    db.commit.assert_awaited_once()
