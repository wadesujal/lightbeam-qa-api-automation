import uuid


def create_order_payload(**overrides) -> dict:
    """Independently generated, non-colliding order payload for every test.
    Pass overrides (e.g. items=[]) to build negative/boundary cases without duplicating this."""
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
    """Mirrors the server's totalAmount formula independently, computed purely from
    the request we sent -- tests must never trust the server's own reported total blindly."""
    return sum(item["quantity"] * item["unitPrice"] for item in items)


def random_credentials() -> dict:
    """The mock server only checks that username/apiKey are present (see TEST_PLAN.md) --
    it does not validate their value -- so random, non-colliding values are sufficient."""
    return {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "apiKey": f"key_{uuid.uuid4().hex[:12]}",
    }
