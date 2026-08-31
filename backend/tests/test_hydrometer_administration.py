from datetime import date
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.routers.hydrometers import (
    delete_hydrometer,
    register_existing_hydrometer_baseline,
)
from app.schemas.hydrometer import HydrometerAdministrativeBaselineRequest


CUSTOMER_ID = UUID("11111111-1111-1111-1111-111111111111")
HYDROMETER_ID = UUID("22222222-2222-2222-2222-222222222222")
ADMIN_ID = UUID("33333333-3333-3333-3333-333333333333")


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _pending_hydrometer() -> Hydrometer:
    customer = Customer(id=CUSTOMER_ID, has_hydrometer=True, status="active")
    hydrometer = Hydrometer(
        id=HYDROMETER_ID,
        customer_id=CUSTOMER_ID,
        code="000001",
        last_reading_value=0,
        last_reading_date=None,
    )
    hydrometer.customer = customer
    return hydrometer


class ExistingHydrometerAdministrationTest(IsolatedAsyncioTestCase):
    async def test_existing_pending_meter_accepts_administrative_baseline(self):
        hydrometer = _pending_hydrometer()
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(hydrometer), _result(None)])
        admin = MagicMock(id=ADMIN_ID)
        request = HydrometerAdministrativeBaselineRequest(
            value=90.645,
            baseline_date=date(2026, 8, 30),
        )

        with (
            patch(
                "app.routers.hydrometers.register_administrative_baseline",
                AsyncMock(),
            ) as register,
            patch(
                "app.routers.hydrometers._fetch_hydrometer_response",
                AsyncMock(return_value=hydrometer),
            ),
        ):
            result = await register_existing_hydrometer_baseline(
                str(HYDROMETER_ID),
                request,
                db,
                admin,
            )

        assert result is hydrometer
        register.assert_awaited_once()
        assert register.await_args.kwargs["value"] == 90.645
        assert register.await_args.kwargs["captured_at"].date() == date(2026, 8, 30)

    async def test_unused_meter_can_be_deleted_and_customer_returns_to_fixed_billing(self):
        hydrometer = _pending_hydrometer()
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[
            _result(hydrometer),
            _result(None),
            _result(None),
            _result(None),
        ])
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        response = await delete_hydrometer(
            str(HYDROMETER_ID),
            db,
            MagicMock(id=ADMIN_ID),
        )

        assert response.status_code == 204
        db.delete.assert_awaited_once_with(hydrometer)
        assert hydrometer.customer.has_hydrometer is False

