"""YAML-driven creation/validation cases, plus two direct tests
(totalAmount correctness, missing correlation ID) that need computed
values rather than a fixed expected field."""

import pytest

from utilities.api_client import OrderClient
from utilities.data_loader import load_cases
from utilities.payload_builders import compute_expected_total, create_order_payload
from utilities.soft_assert import SoftAssert

CASES = load_cases("orders_create.yaml")


def _build_payload(case: dict) -> dict:
    overrides = dict(case.get("overrides") or {})
    drop_fields = overrides.pop("drop", [])
    payload = create_order_payload(**overrides)
    for field in drop_fields:
        payload.pop(field, None)
    return payload


@pytest.mark.orders
@pytest.mark.parametrize("case", CASES)
def test_order_creation(order_client, case, step_log):
    sa = SoftAssert(step_log)
    payload = _build_payload(case)

    with step_log.step(f"POST /orders ({case['id']})"):
        response = order_client.create_order(payload)

    exp = case["expected"]
    sa.equals(response.status_code, exp["status"], "status code")
    body = response.json()

    if exp["status"] == 202:
        for field in ("orderId", "status", "totalAmount", "createdAt"):
            sa.check(field in body, f"response includes '{field}'")
        sa.equals(body.get("status"), exp["order_status"], "initial status")
        sa.equals(
            body.get("totalAmount"),
            pytest.approx(compute_expected_total(payload["items"])),
            "totalAmount matches independently computed total",
        )
    else:
        sa.check("error" in body, "error field present")

    sa.assert_all()


@pytest.mark.orders
def test_create_order_without_correlation_id_returns_400(order_client):
    response = order_client.create_order(create_order_payload(), include_correlation_id=False)
    assert response.status_code == 400, response.text
    assert "error" in response.json()


@pytest.mark.orders
def test_create_order_without_auth_returns_401(settings):
    client = OrderClient(settings=settings, token=None)
    response = client.create_order(create_order_payload())
    assert response.status_code == 401, response.text
