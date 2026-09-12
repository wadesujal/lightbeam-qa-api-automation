"""Auth: the YAML cases cover the 400 validation paths; the success path
and authorization-enforcement checks are direct pytest functions since
they need to inspect the token itself, not just a status code."""

import pytest

from utilities.api_client import OrderClient
from utilities.data_loader import load_cases
from utilities.payload_builders import random_credentials
from utilities.soft_assert import SoftAssert

CASES = load_cases("auth.yaml")


@pytest.mark.smoke
class TestLogin:
    @pytest.mark.title(
        "Validate that the login API returns a bearer token and expiry for valid credentials"
    )
    def test_login_with_valid_credentials_returns_token(self, auth_client, step_log):
        sa = SoftAssert(step_log)
        creds = random_credentials()

        with step_log.step("POST /auth/login with valid credentials"):
            response = auth_client.login(creds["username"], creds["apiKey"])

        sa.equals(response.status_code, 200, "status code")
        body = response.json()
        sa.check(bool(body.get("token")), "response includes a non-empty token")
        sa.check(isinstance(body.get("token"), str), "token is a string")
        # The documented contract is a token *plus* its lifetime -- a client that
        # can't tell when the token expires can't refresh it.
        sa.check("expiresIn" in body, "response includes 'expiresIn'")
        sa.check(isinstance(body.get("expiresIn"), int), "expiresIn is an integer")
        sa.check((body.get("expiresIn") or 0) > 0, "expiresIn is a positive lifetime")
        sa.assert_all()

    @pytest.mark.title(
        "Validate that a freshly issued token is accepted on a protected route"
    )
    def test_login_token_is_accepted_on_a_protected_route(self, auth_client, settings):
        creds = random_credentials()
        token = auth_client.login(creds["username"], creds["apiKey"]).json()["token"]

        with OrderClient(settings=settings, token=token) as client:
            response = client.get_order("ORD-nonexistent-but-authenticated")

        # 404 proves the request got past checkAuth and into the handler;
        # asserting the exact code (not just "not 401") also catches a token
        # that is accepted but routes the caller somewhere unexpected.
        assert response.status_code == 404, (
            f"A freshly issued token should reach the handler and 404 on an unknown "
            f"order, got {response.status_code}: {response.text}"
        )

    @pytest.mark.parametrize("case", CASES)
    def test_login_validation(self, auth_client, case, step_log):
        sa = SoftAssert(step_log)
        with step_log.step(f"POST /auth/login ({case['id']})"):
            body = case["request"]["body"]
            response = auth_client.login(body.get("username"), body.get("apiKey"))

        sa.equals(response.status_code, case["expected"]["status"], "status code")
        sa.check("error" in response.json(), "error field present")
        sa.assert_all()


@pytest.mark.regression
class TestAuthorizationEnforcement:
    """checkAuth only verifies an 'Authorization: Bearer <anything>' header is
    present -- it never validates the token's value (confirmed in server.js
    and documented in TEST_PLAN.md). So the only genuine 401 triggers are a
    missing Authorization header or a non-Bearer scheme."""

    @pytest.mark.title(
        "Validate that a protected route returns 401 when no Authorization header is sent"
    )
    def test_protected_route_without_token_returns_401(self, anonymous_order_client):
        response = anonymous_order_client.get_order("ORD-00000")
        assert response.status_code == 401, response.text
        assert "error" in response.json()

    @pytest.mark.title(
        "Validate that a protected route returns 401 for a non-Bearer authorization scheme"
    )
    def test_protected_route_with_non_bearer_scheme_returns_401(self, anonymous_order_client):
        response = anonymous_order_client.get(
            "/orders/ORD-00000", headers={"Authorization": "Basic sometoken"}
        )
        assert response.status_code == 401, response.text
