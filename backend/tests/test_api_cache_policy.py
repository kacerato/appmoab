import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.background import BackgroundTasks
from starlette.requests import Request
from starlette.responses import Response

from app.models.hydrometer import Hydrometer
from app.routers.hydrometers import disconnect_hydrometer, reconnect_hydrometer
from app.schemas.hydrometer import HydrometerDisconnectRequest, HydrometerReconnectRequest
from app.utils.middleware import _cache_control


def _request(path: str, method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": []})


def test_hydrometer_reads_are_never_http_cached() -> None:
    response = Response(status_code=200)

    assert _cache_control(_request("/api/hydrometers"), response) == "no-store"
    assert _cache_control(_request("/api/hydrometers/00000000-0000-0000-0000-000000000000"), response) == "no-store"


def test_mutations_are_never_http_cached() -> None:
    response = Response(status_code=200)

    assert _cache_control(_request("/api/hydrometers/example/disconnect", "POST"), response) == "no-store"


@pytest.mark.asyncio
async def test_disconnect_is_committed_before_the_success_response_is_built() -> None:
    hydrometer = Hydrometer(id=uuid.uuid4(), customer_id=uuid.uuid4(), code="1001")
    result = MagicMock()
    result.scalar_one_or_none.return_value = hydrometer
    db = AsyncMock()
    db.execute.return_value = result
    call_order: list[str] = []
    db.flush.side_effect = lambda: call_order.append("flush")
    db.commit.side_effect = lambda: call_order.append("commit")

    async def fetch_updated(*_args: object) -> Hydrometer:
        call_order.append("fetch")
        return hydrometer

    with patch("app.routers.hydrometers._fetch_hydrometer_response", side_effect=fetch_updated):
        response = await disconnect_hydrometer(
            str(hydrometer.id),
            HydrometerDisconnectRequest(reason="Teste"),
            db=db,
            admin=MagicMock(),
        )

    assert response is hydrometer
    assert call_order == ["flush", "commit", "fetch"]


@pytest.mark.asyncio
async def test_disconnect_keeps_customer_active_when_another_meter_is_active() -> None:
    customer = MagicMock()
    customer.status = "active"
    hydrometer = Hydrometer(id=uuid.uuid4(), customer_id=uuid.uuid4(), code="1003", is_active=True)
    hydrometer.customer = customer
    meter_result = MagicMock()
    meter_result.scalar_one_or_none.return_value = hydrometer
    sibling_result = MagicMock()
    sibling_result.scalar_one_or_none.return_value = uuid.uuid4()
    db = AsyncMock()
    db.execute.side_effect = [meter_result, sibling_result]

    with patch("app.routers.hydrometers._fetch_hydrometer_response", return_value=hydrometer):
        await disconnect_hydrometer(
            str(hydrometer.id),
            HydrometerDisconnectRequest(reason="Teste"),
            db=db,
            admin=MagicMock(),
        )

    assert hydrometer.is_active is False
    assert customer.status == "active"


@pytest.mark.asyncio
async def test_reading_only_reconnect_commits_without_creating_invoice() -> None:
    customer = MagicMock()
    customer.status = "disconnected"
    hydrometer = Hydrometer(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        code="1002",
        is_active=False,
    )
    hydrometer.customer = customer
    result = MagicMock()
    result.scalar_one_or_none.return_value = hydrometer
    no_existing_charge = MagicMock()
    no_existing_charge.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.side_effect = [result, no_existing_charge]
    call_order: list[str] = []
    db.flush.side_effect = lambda: call_order.append("flush")
    db.commit.side_effect = lambda: call_order.append("commit")

    async def fetch_updated(*_args: object) -> Hydrometer:
        call_order.append("fetch")
        return hydrometer

    with patch("app.routers.hydrometers._fetch_hydrometer_response", side_effect=fetch_updated):
        response = await reconnect_hydrometer(
            str(hydrometer.id),
            BackgroundTasks(),
            HydrometerReconnectRequest(mode="reading_only"),
            db=db,
            admin=MagicMock(),
        )

    assert response is hydrometer
    assert hydrometer.is_active is True
    assert customer.status == "active"
    assert db.execute.await_count == 2
    db.add.assert_not_called()
    assert call_order == ["flush", "commit", "fetch"]


def test_reconnect_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        HydrometerReconnectRequest(mode="unexpected")
