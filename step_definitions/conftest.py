"""Per-test fixtures: settings and the three resource clients.

auth_token logs in once per session and is reused everywhere (any
non-empty username/apiKey is accepted by the mock server -- see
TEST_PLAN.md -- so there's nothing gained by logging in per test)."""

import pytest

from config.settings import Settings
from utilities.api_client import AuthClient, ExportClient, OrderClient
from utilities.payload_builders import random_credentials


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.load()


@pytest.fixture(scope="session")
def auth_client(settings) -> AuthClient:
    return AuthClient(settings=settings)


@pytest.fixture(scope="session")
def auth_token(auth_client) -> str:
    creds = random_credentials()
    response = auth_client.login(creds["username"], creds["apiKey"])
    assert response.status_code == 200, f"Login failed unexpectedly: {response.text}"
    token = response.json().get("token")
    assert token, "Login response did not include a token"
    return token


@pytest.fixture
def order_client(settings, auth_token) -> OrderClient:
    return OrderClient(settings=settings, token=auth_token)


@pytest.fixture
def export_client(settings, auth_token) -> ExportClient:
    return ExportClient(settings=settings, token=auth_token)
