"""Property-based invariant: for ANY list of items the server accepts,
totalAmount must equal sum(quantity * unitPrice), not just for the
hand-picked examples in orders_create.yaml.

Adopted from the reference framework's use of Hypothesis to check
invariants across input space that hand-written cases can't cover. Uses
pytest.importorskip so a missing `hypothesis` install (e.g. in a sandboxed
environment with no package-registry access) skips this file cleanly
instead of breaking collection for the rest of the suite -- once
`pip install -r requirements.txt` runs normally this test runs for real.
"""

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from utilities.payload_builders import compute_expected_total, create_order_payload

item_strategy = st.fixed_dictionaries({
    "sku": st.text(min_size=1, max_size=12, alphabet=st.characters(whitelist_categories=("Lu", "Nd"))),
    "quantity": st.integers(min_value=1, max_value=100),
    "unitPrice": st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False),
})


@pytest.mark.invariant
@pytest.mark.property
@hyp_settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(items=st.lists(item_strategy, min_size=1, max_size=8))
def test_total_amount_holds_for_any_item_list(order_client, items):
    payload = create_order_payload(items=items)
    response = order_client.create_order(payload)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["totalAmount"] == pytest.approx(compute_expected_total(items)), (
        f"totalAmount invariant broken for items={items}: "
        f"server={body['totalAmount']}, expected={compute_expected_total(items)}"
    )
