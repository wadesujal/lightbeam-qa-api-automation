# Test Plan & Traceability Matrix

Last verified run: **35/35 passed** — 30 fast tests in <1s, full suite (including real async
waits) in ~113s, against a live instance of the vendored mock server. Re-run twice consecutively
with no flakiness or leftover-state issues observed.

## Confirmed server contract (read directly from `mock-server/server.js`)

| Area | Confirmed behavior |
|---|---|
| Auth | `checkAuth` only verifies the `Authorization` header starts with `"Bearer "` — the token value itself is never validated. `/auth/login` accepts any non-empty `username`/`apiKey`. |
| Correlation ID | Must be present and non-empty on `POST /orders`; not echoed, not format-checked. |
| Order validation | Presence-only: missing `customerId`/`items`(non-empty array)/`shippingAddress` → 400. No range validation on `quantity`/`unitPrice`. |
| Order state | Computed live from `createdTimestamp` on every read: `>=15000ms` → COMPLETED, `>=5000ms` → PROCESSING, else PENDING. |
| Cancellation | Sets `CANCELLED` (sticky, never advances again). 409 only if already COMPLETED. Cancelling twice succeeds twice (200, not idempotent-error). |
| Exports | No request validation. Status COMPLETED once `>=60000ms` elapsed. Download: 400 while processing, 200 + static hardcoded CSV once complete. |
| Errors | All error responses are `{ "error": "<message>" }`. |

## Traceability matrix

| Requirement (assignment table) | Test(s) |
|---|---|
| POST /auth/login returns Bearer token | `test_auth.py::TestLogin::test_login_with_valid_credentials_returns_token` |
| Token required for protected routes | `test_auth.py::TestAuthorizationEnforcement::test_protected_route_without_token_returns_401`, `test_protected_route_with_non_bearer_scheme_returns_401` |
| Token is actually usable | `test_auth.py::TestLogin::test_login_token_is_accepted_on_a_protected_route` |
| Login negative/validation cases | `test_auth.py::TestLogin::test_login_missing_required_field_returns_400[*]`, `test_login_with_empty_body_returns_400` |
| POST /orders → 202, PENDING | `test_orders.py::TestCreateOrder::test_create_order_returns_202_with_pending_status` |
| totalAmount = sum(qty × price) | `test_orders.py::TestCreateOrder::test_total_amount_is_calculated_correctly`, `test_total_amount_with_decimal_pricing_is_correct` |
| X-Correlation-ID required | `test_orders.py::TestCreateOrder::test_create_order_without_correlation_id_returns_400` |
| Orders auth-protected | `test_orders.py::TestCreateOrder::test_create_order_without_auth_returns_401` |
| Orders payload validation | `test_orders.py::TestCreateOrder::test_create_order_missing_required_field_returns_400[*]`, `test_create_order_with_empty_items_returns_400` |
| GET /orders/:id state machine PENDING→PROCESSING→COMPLETED | `test_orders.py::TestOrderStateTransition::test_order_transitions_pending_to_processing_to_completed` |
| GET is read-only (no self-mutation) | `test_orders.py::TestOrderRetrieval::test_get_order_does_not_itself_mutate_state` |
| GET unknown order → 404 / auth enforced | `test_orders.py::TestOrderRetrieval::test_get_nonexistent_order_returns_404`, `test_get_order_without_auth_returns_401` |
| DELETE cancels during PENDING | `test_orders.py::TestCancelOrder::test_cancel_order_while_pending_succeeds` |
| DELETE cancels during PROCESSING | `test_orders.py::TestCancelOrder::test_cancel_order_while_processing_succeeds` |
| DELETE → 409 once COMPLETED | `test_orders.py::TestCancelOrder::test_cancel_order_after_completed_returns_409` |
| Cancel-twice / cancel-unknown / cancelled-stays-cancelled | `test_cancelling_twice_is_idempotent`, `test_cancel_nonexistent_order_returns_404`, `test_cancelled_order_never_advances_state` |
| POST /exports → 202 + jobId | `test_exports.py::TestCreateExport::test_create_export_returns_202_with_job_id` |
| Exports auth-protected | `test_create_export_without_auth_returns_401`, and the `_without_auth_returns_401` tests on status/download |
| GET /exports/:jobId PROCESSING → COMPLETED (~60s) | `test_exports.py::TestDownloadExport::test_export_completes_and_download_returns_valid_csv` (covers both the transition and the resulting download in one real-time wait) |
| Download 400 while incomplete | `test_exports.py::TestDownloadExport::test_download_before_completion_returns_400` |
| Download 200 + text/csv + payload once complete | `test_exports.py::TestDownloadExport::test_export_completes_and_download_returns_valid_csv` |
| Unknown jobId → 404 (status & download) | `test_status_for_nonexistent_job_returns_404`, `test_download_for_nonexistent_job_returns_404` |

## Assumptions

- The mock server's timing constants (5s/15s/60s) are treated as measured from resource-creation
  time (confirmed directly in source — not an assumption after all, but called out since the
  assignment table alone doesn't state this).
- No rate limiting or concurrency limits are assumed or tested, since the server implements none.
- CSV content assertions check structure (header row, column names, `Content-Type`), not the
  specific order data, because the server's CSV payload is static/hardcoded regardless of what
  orders exist.

## Markers

`smoke` (fast high-value checks), `orders`, `exports`, `regression` (auth-enforcement edge cases),
`slow` (tests that wait out real async timing, ~15-75s). Run `pytest -m "not slow"` for a fast
PR-gate subset and the full `pytest` for a complete nightly-style run.
