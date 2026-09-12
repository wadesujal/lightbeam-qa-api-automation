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
    """Transport-level failure (connection error, exhausted retries, or a
    response body that isn't valid JSON where JSON was expected) -- never
    raised for HTTP error status codes, which tests assert on directly."""


class BaseClient:
    """Shared HTTP plumbing (session, auth header, retry-with-backoff,
    request/response logging) for every resource-specific client below.
    Tests interact with `AuthClient`/`OrderClient`/`ExportClient`, never
    with this class or `requests` directly."""

    def __init__(self, settings: Settings = None, token: str = None):
        """Build a client bound to `settings` (defaults to `Settings.load()`)
        and, optionally, a bearer `token` to send on every request."""
        self.settings = settings or Settings.load()
        self.base_url = self.settings.base_url.rstrip("/")
        self.token = token
        self.timeout = self.settings.request_timeout_seconds
        self.session = requests.Session()

    def set_token(self, token: str) -> None:
        """Attach or replace the bearer token used on subsequent requests."""
        self.token = token

    def _headers(self, extra_headers: dict = None) -> dict:
        """Build the default JSON + Authorization headers for a request,
        merged with any `extra_headers` (which take precedence)."""
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
        """Send one HTTP request, retrying with backoff on transport errors
        or 5xx responses (never on a 4xx, which is a real test outcome).

        Raises:
            ApiError: if every attempt (the initial one plus `retries`)
                fails with a network-level error.
        """
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
        """Send a GET request to `path` (see `request` for retry/backoff behavior)."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: dict = None, **kwargs) -> requests.Response:
        """Send a POST request to `path` with an optional JSON body."""
        return self.request("POST", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        """Send a DELETE request to `path`."""
        return self.request("DELETE", path, **kwargs)

    @staticmethod
    def safe_json(response: requests.Response) -> dict:
        """Parse `response`'s body as JSON, raising a clear `ApiError`
        (instead of an opaque `json.JSONDecodeError`) if the server
        returned a non-JSON or empty body where JSON was expected."""
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(
                f"Expected JSON body from {response.request.method} {response.request.url} "
                f"(status {response.status_code}), got: {response.text[:200]!r}"
            ) from exc


class AuthClient(BaseClient):
    """Client for the `/auth/login` endpoint."""

    def login(self, username: str, api_key: str):
        """POST credentials to `/auth/login`. The mock server accepts any
        non-empty `username`/`api_key` pair -- see TEST_PLAN.md."""
        return self.post("/auth/login", json_body={"username": username, "apiKey": api_key})


class OrderClient(BaseClient):
    """Client for the `/orders` resource: create, fetch, and cancel."""

    def create_order(self, payload: dict, correlation_id: str = None, include_correlation_id: bool = True):
        """POST a new order. `X-Correlation-ID` is attached automatically
        (a random UUID by default) unless `include_correlation_id=False`,
        which is how the "missing correlation ID" negative case is built."""
        headers = {}
        if include_correlation_id:
            headers["X-Correlation-ID"] = correlation_id or str(uuid.uuid4())
        return self.post("/orders", json_body=payload, headers=headers)

    def get_order(self, order_id: str):
        """GET the current state of one order by id."""
        return self.get(f"/orders/{order_id}")

    def delete_order(self, order_id: str):
        """DELETE (cancel) an order by id. Cancelling an already-cancelled
        order still returns 200 -- CANCELLED is a sticky terminal state."""
        return self.delete(f"/orders/{order_id}")


class ExportClient(BaseClient):
    """Client for the async export job resource: create, poll, download."""

    def create_export(self):
        """POST a new export job."""
        return self.post("/exports")

    def get_status(self, job_id: str):
        """GET the current status of an export job by id."""
        return self.get(f"/exports/{job_id}")

    def download(self, job_id: str):
        """GET the completed export's CSV content. Note: the mock server
        returns a static, hardcoded CSV regardless of the order data
        created during the test -- see TEST_PLAN.md."""
        return self.get(f"/exports/{job_id}/download")
