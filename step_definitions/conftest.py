"""Per-test fixtures: settings, the three authenticated resource clients,
and their unauthenticated counterparts used by the 401 tests.

`auth_token` logs in once per session and is reused everywhere (any
non-empty username/apiKey is accepted by the mock server -- see
TEST_PLAN.md -- so there's nothing gained by logging in per test).

Every client fixture yields and then closes its `requests.Session`, so a
full suite run doesn't leak pooled sockets or emit ResourceWarnings.
"""

from collections.abc import Iterator

import pytest

from config.settings import Settings
from utilities.api_client import AuthClient, ExportClient, OrderClient
from utilities.payload_builders import random_credentials


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Load settings once per session (env selected via `$TEST_ENV`)."""
    return Settings.load()


@pytest.fixture(scope="session")
def auth_client(settings) -> Iterator[AuthClient]:
    """An unauthenticated client for the `/auth/login` endpoint itself."""
    client = AuthClient(settings=settings)
    yield client
    client.close()


@pytest.fixture(scope="session")
def auth_token(auth_client) -> str:
    """Log in once per session with random (but valid-shaped) credentials
    and return the bearer token, reused by every authenticated test."""
    creds = random_credentials()
    response = auth_client.login(creds["username"], creds["apiKey"])
    assert response.status_code == 200, f"Login failed unexpectedly: {response.text}"
    token = response.json().get("token")
    assert token, "Login response did not include a token"
    return token


@pytest.fixture
def order_client(settings, auth_token) -> Iterator[OrderClient]:
    """A fresh, authenticated `OrderClient` for each test."""
    client = OrderClient(settings=settings, token=auth_token)
    yield client
    client.close()


@pytest.fixture
def export_client(settings, auth_token) -> Iterator[ExportClient]:
    """A fresh, authenticated `ExportClient` for each test."""
    client = ExportClient(settings=settings, token=auth_token)
    yield client
    client.close()


@pytest.fixture
def anonymous_order_client(settings) -> Iterator[OrderClient]:
    """An `OrderClient` with no bearer token, for the 401 enforcement
    tests. A shared fixture rather than an inline construction per test so
    the session is always closed and the intent is obvious at the call site."""
    client = OrderClient(settings=settings, token=None)
    yield client
    client.close()


@pytest.fixture
def anonymous_export_client(settings) -> Iterator[ExportClient]:
    """An `ExportClient` with no bearer token, for the 401 enforcement tests."""
    client = ExportClient(settings=settings, token=None)
    yield client
    client.close()
