import pytest

from src.builders.payload_builders import random_credentials
from src.clients.order_client import OrderClient


pytestmark = pytest.mark.smoke


class TestLogin:
    def test_login_with_valid_credentials_returns_token(self, auth_client):
        creds = random_credentials()
        response = auth_client.login(creds["username"], creds["apiKey"])

        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("token"), f"Expected a non-empty token, got: {body}"
        assert isinstance(body["token"], str)

    def test_login_token_is_accepted_on_a_protected_route(self, auth_client):
        creds = random_credentials()
        token = auth_client.login(creds["username"], creds["apiKey"]).json()["token"]

        client = OrderClient(token=token)
        response = client.get_order("ORD-nonexistent-but-authenticated")
        # 404 (not found) proves auth passed; 401 would mean the token was rejected.
        assert response.status_code != 401, "A freshly issued token was rejected by a protected route"

    @pytest.mark.parametrize("missing_field", ["username", "apiKey"])
    def test_login_missing_required_field_returns_400(self, auth_client, missing_field):
        creds = random_credentials()
        del creds[missing_field]
        response = auth_client.login(creds.get("username"), creds.get("apiKey"))

        assert response.status_code == 400, response.text
        assert "error" in response.json()

    def test_login_with_empty_body_returns_400(self, auth_client):
        response = auth_client.post("/auth/login", json_body={})
        assert response.status_code == 400, response.text


@pytest.mark.regression
class TestAuthorizationEnforcement:
    """The mock server's checkAuth middleware only verifies that an
    'Authorization: Bearer <anything>' header is present -- it does not validate
    the token's value (see TEST_PLAN.md). So the only genuine 401 triggers are:
    a missing Authorization header, or one that doesn't start with 'Bearer '."""

    def test_protected_route_without_token_returns_401(self):
        client = OrderClient(token=None)
        response = client.get_order("ORD-00000")
        assert response.status_code == 401, response.text
        assert "error" in response.json()

    def test_protected_route_with_non_bearer_scheme_returns_401(self):
        client = OrderClient()
        response = client.get("/orders/ORD-00000", headers={"Authorization": "Basic sometoken"})
        assert response.status_code == 401, response.text
