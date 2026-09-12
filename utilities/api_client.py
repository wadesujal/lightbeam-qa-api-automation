"""HTTP clients for the mock service.

Unlike the reference framework's dual-mode client (in-process Flask test
client OR real HTTP), this assignment's SUT is only ever reached over real
HTTP -- there is no importable in-process app to wrap. So there is a single
BaseClient centralizing session/auth/retry/logging, with one thin subclass
per resource. Tests never call `requests.*` directly.
"""

import time
import uuid

import requests

from config.settings import Settings
from utilities.logger import get_logger, mask_sensitive

logger = get_logger(__name__)


class ApiError(Exception):
    """Transport-level failure (connection error, exhausted retries) --
    never raised for HTTP error status codes, which tests assert on directly."""


class BaseClient:
    def __init__(self, settings: Settings = None, token: str = None):
        self.settings = settings or Settings.load()
        self.base_url = self.settings.base_url.rstrip("/")
        self.token = token
        self.timeout = self.settings.request_timeout_seconds
        self.session = requests.Session()

    def set_token(self, token: str) -> None:
        self.token = token

    def _headers(self, extra_headers: dict = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def request(
        self,
        method: str,
        path: str,
        headers: dict = None,
        json_body: dict = None,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        **kwargs,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        merged_headers = self._headers(headers)

        last_exc = None
        for attempt in range(retries + 1):
            start = time.monotonic()
            try:
                response = self.session.request(
                    method, url, headers=merged_headers, json=json_body,
                    timeout=self.timeout, **kwargs,
                )
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.info(
                    "%s %s -> %s (%.0fms)%s",
                    method, path, response.status_code, elapsed_ms,
                    f" corr_id={merged_headers['X-Correlation-ID']}" if "X-Correlation-ID" in merged_headers else "",
                )
                # Only retry genuine transport/server hiccups -- never a 4xx a test cares about.
                if response.status_code >= 500 and attempt < retries:
                    time.sleep(backoff_seconds * (attempt + 1))
                    continue
                return response
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Network error on %s %s (attempt %d/%d): %s",
                    method, path, attempt + 1, retries + 1, mask_sensitive(str(exc)),
                )
                time.sleep(backoff_seconds * (attempt + 1))

        raise ApiError(f"Request failed after {retries + 1} attempts: {method} {url}") from last_exc

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: dict = None, **kwargs) -> requests.Response:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)


class AuthClient(BaseClient):
    def login(self, username: str, api_key: str):
        return self.post("/auth/login", json_body={"username": username, "apiKey": api_key})


class OrderClient(BaseClient):
    def create_order(self, payload: dict, correlation_id: str = None, include_correlation_id: bool = True):
        headers = {}
        if include_correlation_id:
            headers["X-Correlation-ID"] = correlation_id or str(uuid.uuid4())
        return self.post("/orders", json_body=payload, headers=headers)

    def get_order(self, order_id: str):
        return self.get(f"/orders/{order_id}")

    def delete_order(self, order_id: str):
        return self.delete(f"/orders/{order_id}")


class ExportClient(BaseClient):
    def create_export(self):
        return self.post("/exports")

    def get_status(self, job_id: str):
        return self.get(f"/exports/{job_id}")

    def download(self, job_id: str):
        return self.get(f"/exports/{job_id}/download")
