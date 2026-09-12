import time

import requests

from config.config import config
from src.utils.logger import get_logger, mask_sensitive

logger = get_logger(__name__)


class ApiError(Exception):
    """Raised for transport-level failures (connection errors, exhausted retries) --
    never for HTTP error status codes, which tests are expected to assert on directly."""


class BaseClient:
    """Centralizes base URL, session reuse, auth injection, timeout, retry-on-network-error,
    and request/response logging. No test and no subclass should call `requests.*` directly --
    everything goes through this class so behavior (auth, logging, retries) stays in one place."""

    def __init__(self, base_url: str = None, token: str = None, timeout: float = None):
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.token = token
        self.timeout = timeout or config.REQUEST_TIMEOUT
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
