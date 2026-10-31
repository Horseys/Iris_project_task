from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TABLE_CODE = "52311-01-04-4"
DEFAULT_BASE_URL = "https://www.regionalstatistik.de/gngServer"
SOURCE_TABLE_URL = (
    "https://www.regionalstatistik.de/datenbank/online/statistic/"
    f"52311/table/{TABLE_CODE}"
)


class GenesisAPIError(RuntimeError):
    """Raised when the Regionaldatenbank API cannot return a valid response."""


@dataclass(frozen=True)
class GenesisPayload:
    structure: dict[str, Any]
    data: dict[str, Any]


class GenesisRegionalClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.username = username or os.getenv("GENESIS_USERNAME")
        self.password = password or os.getenv("GENESIS_PASSWORD")
        if bool(self.username) != bool(self.password):
            raise ValueError(
                "Set both GENESIS_USERNAME and GENESIS_PASSWORD, or neither"
            )
        self.session = requests.Session()
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        if self.username and self.password:
            self.session.auth = (self.username, self.password)

    def fetch_payload(self) -> GenesisPayload:
        table_url = f"{self.base_url}/api/rest/tables/{TABLE_CODE}"
        try:
            structure = self._get_json(f"{table_url}/structure")
            data = self._get_json(f"{table_url}/data")
        except requests.RequestException as exc:
            raise GenesisAPIError(f"GENESIS request failed: {exc}") from exc
        except ValueError as exc:
            raise GenesisAPIError(f"GENESIS returned invalid JSON: {exc}") from exc

        if not isinstance(structure, dict) or not isinstance(data, dict):
            raise GenesisAPIError("GENESIS response must contain JSON objects")
        return GenesisPayload(structure=structure, data=data)

    def _get_json(self, url: str) -> Any:
        response = self.session.get(
            url,
            params={"language": "de"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
