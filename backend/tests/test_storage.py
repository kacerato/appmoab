from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.utils import storage


def test_r2_client_is_reused_between_artifact_uploads():
    client = object()
    boto3 = SimpleNamespace(client=Mock(return_value=client))
    storage._r2_client.cache_clear()

    try:
        with patch.dict("sys.modules", {"boto3": boto3}):
            assert storage._r2_client() is client
            assert storage._r2_client() is client
    finally:
        storage._r2_client.cache_clear()

    boto3.client.assert_called_once()
