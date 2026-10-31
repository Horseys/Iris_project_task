from unittest.mock import Mock, call

import pytest
import requests

from task_cre_50.client import (
    DEFAULT_BASE_URL,
    TABLE_CODE,
    GenesisAPIError,
    GenesisRegionalClient,
)


def test_fetch_payload_requests_structure_and_data_with_timeout() -> None:
    client = GenesisRegionalClient(timeout_seconds=7)
    structure = {"table": {"code": TABLE_CODE}}
    data = {"data": []}
    structure_response = Mock()
    structure_response.json.return_value = structure
    data_response = Mock()
    data_response.json.return_value = data
    client.session.get = Mock(side_effect=[structure_response, data_response])

    payload = client.fetch_payload()

    table_url = f"{DEFAULT_BASE_URL}/api/rest/tables/{TABLE_CODE}"
    assert payload.structure is structure
    assert payload.data is data
    assert client.session.get.call_args_list == [
        call(
            f"{table_url}/structure",
            params={"language": "de"},
            timeout=7,
        ),
        call(
            f"{table_url}/data",
            params={"language": "de"},
            timeout=7,
        ),
    ]


def test_fetch_payload_wraps_http_errors() -> None:
    client = GenesisRegionalClient()
    client.session.get = Mock(
        side_effect=requests.Timeout("upstream timed out")
    )

    with pytest.raises(GenesisAPIError, match="GENESIS request failed"):
        client.fetch_payload()


def test_fetch_payload_wraps_json_decode_errors() -> None:
    client = GenesisRegionalClient()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.side_effect = ValueError("invalid JSON")
    client.session.get = Mock(return_value=response)

    with pytest.raises(GenesisAPIError, match="invalid JSON"):
        client.fetch_payload()


def test_fetch_payload_rejects_non_object_response() -> None:
    client = GenesisRegionalClient()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = []
    client.session.get = Mock(return_value=response)

    with pytest.raises(GenesisAPIError, match="JSON objects"):
        client.fetch_payload()


@pytest.mark.parametrize("timeout", [0, -1])
def test_client_rejects_non_positive_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        GenesisRegionalClient(timeout_seconds=timeout)


def test_client_requires_both_credentials(monkeypatch) -> None:
    monkeypatch.setenv("GENESIS_USERNAME", "user")
    monkeypatch.delenv("GENESIS_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="Set both"):
        GenesisRegionalClient()
