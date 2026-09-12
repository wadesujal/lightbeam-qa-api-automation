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

# This script is executed directly (`python scripts/validate_contract.py`), so the
# repo root has to be on sys.path before the first-party imports below can resolve.
# The first-party imports therefore sit after executable code on purpose; a
# package-relative launch would make the CI invocation less obvious than the
# import-order convention is worth.
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings
from utilities.api_client import ApiError, AuthClient, ExportClient, OrderClient
from utilities.logger import configure_stream_logging, get_logger

logger = get_logger(__name__)

# This script runs outside pytest, so nothing else would attach a handler and
# every record below WARNING would be discarded silently.
configure_stream_logging()

REQUIRED_FIELDS = {
    "POST /auth/login": {"token", "expiresIn"},
    "POST /orders": {"orderId", "status", "totalAmount", "createdAt"},
    "GET /orders/:id": {
        "orderId",
        "customerId",
        "items",
        "shippingAddress",
        "totalAmount",
        "status",
        "createdAt",
    },
    "POST /exports": {"jobId", "status", "pollIntervalSeconds"},
    "GET /exports/:id": {"jobId", "status", "downloadUrl"},
}


def _check(label: str, body: dict, errors: list) -> None:
    """Verify `body` contains every field `REQUIRED_FIELDS[label]` expects,
    appending a descriptive message to `errors` (in place) if any are
    missing, and logging success otherwise."""
    required = REQUIRED_FIELDS[label]
    missing = required - set(body.keys())
    if missing:
        errors.append(f"{label}: missing fields {sorted(missing)} in response {body}")
    else:
        logger.info("ok  %s", label)


def main() -> None:
    """Run one login + order + export cycle against the live mock server
    and verify every response includes the fields this framework's tests
    assume are present. Exits non-zero (via `sys.exit`) on any contract
    violation, malformed response, or transport failure, so this can gate
    CI before the real test suite runs."""
    settings = Settings.load()
    errors: list = []

    auth = AuthClient(settings=settings)
    login = auth.login(f"contract-check-{uuid.uuid4().hex[:6]}", "contract-check-key")
    if login.status_code != 200:
        logger.error("FAIL  could not even log in: %s %s", login.status_code, login.text)
        sys.exit(1)
    login_body = AuthClient.safe_json(login)
    _check("POST /auth/login", login_body, errors)
    token = login_body.get("token")
    if not token:
        errors.append("POST /auth/login: response had no usable 'token' -- cannot continue")
        _fail(errors)

    orders = OrderClient(settings=settings, token=token)
    create = orders.create_order(
        {
            "customerId": "contract-check",
            "items": [{"sku": "X", "quantity": 1, "unitPrice": 1.0}],
            "shippingAddress": "n/a",
        },
    )
    if create.status_code != 202:
        errors.append(f"POST /orders: expected 202, got {create.status_code} {create.text}")
    else:
        create_body = OrderClient.safe_json(create)
        _check("POST /orders", create_body, errors)
        order_id = create_body.get("orderId")
        if order_id:
            get_order = orders.get_order(order_id)
            if get_order.status_code != 200:
                errors.append(f"GET /orders/:id: expected 200, got {get_order.status_code}")
            else:
                _check("GET /orders/:id", OrderClient.safe_json(get_order), errors)

    exports = ExportClient(settings=settings, token=token)
    export_create = exports.create_export()
    if export_create.status_code != 202:
        errors.append(f"POST /exports: expected 202, got {export_create.status_code}")
    else:
        export_body = ExportClient.safe_json(export_create)
        _check("POST /exports", export_body, errors)
        job_id = export_body.get("jobId")
        if job_id:
            status = exports.get_status(job_id)
            if status.status_code != 200:
                errors.append(f"GET /exports/:id: expected 200, got {status.status_code}")
            else:
                _check("GET /exports/:id", ExportClient.safe_json(status), errors)

    _fail(errors)
    logger.info("contract OK")


def _fail(errors: list) -> None:
    """Log every collected error and exit(1) if `errors` is non-empty;
    otherwise return normally so `main()` can continue."""
    if errors:
        for e in errors:
            logger.error("FAIL  %s", e)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except ApiError as exc:
        logger.error("FAIL  transport error talking to the mock server: %s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("FAIL  unexpected error while validating the contract")
        sys.exit(1)
