"""Contract gate: every field the test suite assumes the mock server
returns must actually be present. Run as a CI step before the test suite,
so a drifted/replaced mock server fails fast with a clear message instead
of forty confusing test failures.

Adapted from the reference framework's `validate_schema.py` (which checked
a SQL schema) -- this assignment's SUT has no database, so the equivalent
check is against the live HTTP contract instead.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings
from utilities.api_client import AuthClient, ExportClient, OrderClient

REQUIRED_FIELDS = {
    "POST /auth/login": {"token"},
    "POST /orders": {"orderId", "status", "totalAmount", "createdAt"},
    "GET /orders/:id": {"orderId", "customerId", "items", "shippingAddress", "totalAmount", "status"},
    "POST /exports": {"jobId", "status"},
    "GET /exports/:id": {"jobId", "status"},
}


def _check(label: str, body: dict, errors: list) -> None:
    required = REQUIRED_FIELDS[label]
    missing = required - set(body.keys())
    if missing:
        errors.append(f"{label}: missing fields {sorted(missing)} in response {body}")
    else:
        print(f"  ok  {label}")


def main() -> None:
    settings = Settings.load()
    errors: list = []

    auth = AuthClient(settings=settings)
    login = auth.login(f"contract-check-{uuid.uuid4().hex[:6]}", "contract-check-key")
    if login.status_code != 200:
        print(f"FAIL  could not even log in: {login.status_code} {login.text}", file=sys.stderr)
        sys.exit(1)
    _check("POST /auth/login", login.json(), errors)
    token = login.json()["token"]

    orders = OrderClient(settings=settings, token=token)
    create = orders.create_order(
        {"customerId": "contract-check", "items": [{"sku": "X", "quantity": 1, "unitPrice": 1.0}],
         "shippingAddress": "n/a"},
    )
    if create.status_code != 202:
        errors.append(f"POST /orders: expected 202, got {create.status_code} {create.text}")
    else:
        _check("POST /orders", create.json(), errors)
        order_id = create.json()["orderId"]
        get_order = orders.get_order(order_id)
        if get_order.status_code != 200:
            errors.append(f"GET /orders/:id: expected 200, got {get_order.status_code}")
        else:
            _check("GET /orders/:id", get_order.json(), errors)

    exports = ExportClient(settings=settings, token=token)
    export_create = exports.create_export()
    if export_create.status_code != 202:
        errors.append(f"POST /exports: expected 202, got {export_create.status_code}")
    else:
        _check("POST /exports", export_create.json(), errors)
        job_id = export_create.json()["jobId"]
        status = exports.get_status(job_id)
        if status.status_code != 200:
            errors.append(f"GET /exports/:id: expected 200, got {status.status_code}")
        else:
            _check("GET /exports/:id", status.json(), errors)

    if errors:
        for e in errors:
            print(f"FAIL  {e}", file=sys.stderr)
        sys.exit(1)
    print("contract OK")


if __name__ == "__main__":
    main()
