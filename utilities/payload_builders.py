"""Test data factories, independent of any YAML case -- used both by the
YAML-driven tests (to fill in dynamic fields like customerId) and by the
non-YAML lifecycle tests (state transition, cancellation) that need a
freshly created order per test."""

import uuid


def create_order_payload(**overrides) -> dict:
    """Build a valid order-creation payload with sensible defaults
    (a fresh random `customerId`, two line items, a fixed shipping
    address). Any keyword arg overrides or adds a top-level field, which
    is how negative/boundary cases (e.g. `items=[]`) are constructed."""
    default_items = [
        {"sku": "SKU-1001", "quantity": 2, "unitPrice": 19.99},
        {"sku": "SKU-1002", "quantity": 1, "unitPrice": 49.50},
    ]
    payload = {
        "customerId": f"CUST-{uuid.uuid4().hex[:8]}",
        "items": default_items,
        "shippingAddress": "221B Baker Street, London, UK",
    }
    payload.update(overrides)
    return payload


def compute_expected_total(items: list) -> float:
    """Mirrors the server's totalAmount formula independently, computed purely
    from the request sent -- tests must never trust the server's own total blindly."""
    return sum(item["quantity"] * item["unitPrice"] for item in items)


def random_credentials() -> dict:
    """The mock server only checks that username/apiKey are present (see
    TEST_PLAN.md) -- it never validates their value -- so random values suffice."""
    return {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "apiKey": f"key_{uuid.uuid4().hex[:12]}",
    }
