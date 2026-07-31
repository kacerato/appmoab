from sqlalchemy.dialects import postgresql

from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.routers.customers import _active_route_cycles_query
from app.services.reading_cycles import hydrometer_available_for_field


def test_route_query_excludes_inactive_customers_and_hydrometers() -> None:
    sql = str(
        _active_route_cycles_query().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "hydrometers.is_active IS true" in sql
    assert "customers.status = 'active'" in sql


def test_field_capture_requires_active_customer_and_hydrometer() -> None:
    customer = Customer(status="active")
    hydrometer = Hydrometer(is_active=True)
    hydrometer.customer = customer

    assert hydrometer_available_for_field(hydrometer) is True

    customer.status = "disconnected"
    assert hydrometer_available_for_field(hydrometer) is False

    customer.status = "active"
    hydrometer.is_active = False
    assert hydrometer_available_for_field(hydrometer) is False
