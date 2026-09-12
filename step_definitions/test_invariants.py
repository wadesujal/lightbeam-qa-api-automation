"""Property-based invariant: for ANY list of items the server accepts,
totalAmount must equal sum(quantity * unitPrice), not just for the
hand-picked examples in orders_create.yaml.

Adopted from the reference framework's use of Hypothesis to check
invariants across input space that hand-written cases can't cover.
`hypothesis` is a pinned entry in requirements.txt, so it is imported
normally at module scope -- an earlier `pytest.importorskip` guard was a
workaround for a sandbox with no package index, and it had the side effect
of hiding a genuinely missing dependency behind a silent skip.
"""

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from utilities.payload_builders import compute_expected_total, create_order_payload

item_strategy = st.fixed_dictionaries({
    "sku": st.text(min_size=1, max_size=12, alphabet=st.characters(whitelist_categories=("Lu", "Nd"))),
    "quantity": st.integers(min_value=1, max_value=100),
    "unitPrice": st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False),
})


@pytest.mark.invariant
@pytest.mark.property
@pytest.mark.title(
    "Validate that totalAmount equals the sum of quantity x unitPrice for any generated item list"
)
# The Hypothesis decorators stay innermost: markers must be applied to the
# wrapper pytest collects, not to the raw function `given()` wraps.
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
