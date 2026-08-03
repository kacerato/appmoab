from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.tariffs import update_minimum_charge
from app.schemas.tariff import MinimumChargeUpdate


@pytest.mark.asyncio
async def test_minimum_charge_is_updated_for_every_tier() -> None:
    result = MagicMock()
    result.all.return_value = [("tier-1",), ("tier-2",), ("tier-3",)]
    db = AsyncMock()
    db.execute.return_value = result

    response = await update_minimum_charge(
        MinimumChargeUpdate(amount=110),
        db=db,
        admin=MagicMock(),
    )

    assert response.amount == 110
    assert response.updated_tiers == 3
    db.flush.assert_awaited_once()


def test_minimum_charge_must_be_positive() -> None:
    with pytest.raises(ValueError):
        MinimumChargeUpdate(amount=0)
