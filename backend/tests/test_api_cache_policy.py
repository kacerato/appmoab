import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.models.hydrometer import Hydrometer
from app.routers.hydrometers import disconnect_hydrometer
from app.schemas.hydrometer import HydrometerDisconnectRequest
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
