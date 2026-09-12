"""YAML-driven creation/validation cases, plus two direct tests
(totalAmount correctness, missing correlation ID) that need computed
values rather than a fixed expected field."""

import pytest

from utilities.data_loader import load_cases
from utilities.payload_builders import compute_expected_total, create_order_payload
from utilities.soft_assert import SoftAssert

CASES = load_cases("orders_create.yaml")


def _build_payload(case: dict) -> dict:
    """Build the request payload for one YAML case: start from the default
    valid payload, apply `overrides`, then remove any field named in
    `overrides.drop` -- how "missing field" negative cases are expressed
    in YAML without needing a bespoke payload per case."""
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
@pytest.mark.title(
    "Validate that the orders API rejects a request with no X-Correlation-ID header"
)
def test_create_order_without_correlation_id_returns_400(order_client):
    response = order_client.create_order(create_order_payload(), include_correlation_id=False)
    assert response.status_code == 400, response.text
    assert "error" in response.json()


@pytest.mark.orders
@pytest.mark.boundary
@pytest.mark.title(
    "Validate that the orders API rejects a request with an empty X-Correlation-ID header"
)
def test_create_order_with_empty_correlation_id_returns_400(order_client):
    """Header present but empty is a distinct boundary from header absent --
    a server that only checks `'x-correlation-id' in headers` would pass the
    missing-header test above and still accept an untraceable request here."""
    response = order_client.create_order(create_order_payload(), correlation_id="")
    assert response.status_code == 400, response.text
    assert "error" in response.json()


@pytest.mark.orders
@pytest.mark.title(
    "Validate that the orders API returns 401 for an unauthenticated create request"
)
def test_create_order_without_auth_returns_401(anonymous_order_client):
    response = anonymous_order_client.create_order(create_order_payload())
    assert response.status_code == 401, response.text


@pytest.mark.orders
@pytest.mark.regression
class TestKnownServerValidationGaps:
    """Characterization tests: these assert what the mock server *currently*
    does, not what a production order service *should* do.

    Both cases below would be raised as defects against a real service
    (a negative quantity is not a purchasable line; a line with no quantity
    should never yield a null total). They are pinned here deliberately so
    the gap is visible in the report and any future tightening of server-side
    validation shows up as a deliberate, reviewed test change rather than a
    silent behavior drift."""

    @pytest.mark.title(
        "Validate that the orders API currently accepts a negative quantity and returns a negative total (documented defect)"
    )
    def test_negative_quantity_is_currently_accepted(self, order_client):
        payload = create_order_payload(items=[{"sku": "SKU-NEG", "quantity": -2, "unitPrice": 10.0}])
        response = order_client.create_order(payload)

        assert response.status_code == 202, response.text
        assert response.json()["totalAmount"] == pytest.approx(-20.0), (
            "DEFECT (documented): the server accepts a negative quantity and "
            "produces a negative order total instead of rejecting the payload."
        )

    @pytest.mark.title(
        "Validate that the orders API currently returns a null totalAmount for an item with no quantity (documented defect)"
    )
    def test_item_without_quantity_yields_a_null_total(self, order_client):
        payload = create_order_payload(items=[{"sku": "SKU-NOQTY", "unitPrice": 10.0}])
        response = order_client.create_order(payload)

        assert response.status_code == 202, response.text
        assert response.json()["totalAmount"] is None, (
            "DEFECT (documented): a line item with no quantity makes the "
            "reduce() produce NaN, serialized as null, instead of a 400."
        )
