from sqlalchemy import inspect

from app.models.customer import Customer


def test_customer_hydrometers_are_loaded_with_selectin() -> None:
    """Async response serialization must not trigger an implicit lazy query."""
    relationship = inspect(Customer).relationships.hydrometers

    assert relationship.lazy == "selectin"
