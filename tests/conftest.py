import pytest

from src.builders.payload_builders import random_credentials
from src.clients.auth_client import AuthClient
from src.clients.export_client import ExportClient
from src.clients.order_client import OrderClient


@pytest.fixture(scope="session")
def auth_client() -> AuthClient:
    return AuthClient()


@pytest.fixture(scope="session")
def auth_token(auth_client) -> str:
    """Logs in once per test session and reuses the token everywhere else.
    Any non-empty username/apiKey is accepted by the mock server (confirmed in
    server.js and documented in TEST_PLAN.md) -- credentials just need to be present."""
    creds = random_credentials()
    response = auth_client.login(creds["username"], creds["apiKey"])
    assert response.status_code == 200, f"Login failed unexpectedly: {response.text}"
    token = response.json().get("token")
    assert token, "Login response did not include a token"
    return token


@pytest.fixture()
def order_client(auth_token) -> OrderClient:
    return OrderClient(token=auth_token)


@pytest.fixture()
def export_client(auth_token) -> ExportClient:
    return ExportClient(token=auth_token)
