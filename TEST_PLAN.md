# Test Plan & Traceability Matrix

Last verified run: **32/32 executable tests passed** — 27 fast in <1s, full suite (including real
async waits) in ~113s, against a live instance of the vendored mock server. One additional
Hypothesis property test (`test_invariants.py`) is skipped in this sandboxed build environment (no
package-registry access to install `hypothesis`) and runs normally once `pip install -r
requirements.txt` completes elsewhere — see README "Known limitations."

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
| Login negative/validation cases | `test_auth.py::TestLogin::test_login_validation[missing_username\|missing_api_key\|empty_body]` (YAML: `testcases/auth.yaml`) |
| POST /orders → 202, PENDING | `test_orders_create.py::test_order_creation[valid_multi_item_order]` (YAML: `testcases/orders_create.yaml`) |
| totalAmount = sum(qty × price) | `test_order_creation[*]` (every 202 case asserts this) and `test_invariants.py::test_total_amount_holds_for_any_item_list` (property test across randomized inputs) |
| X-Correlation-ID required | `test_orders_create.py::test_create_order_without_correlation_id_returns_400` |
| Orders auth-protected | `test_orders_create.py::test_create_order_without_auth_returns_401` |
| Orders payload validation | `test_order_creation[missing_customer_id\|missing_items\|empty_items_array\|missing_shipping_address]` (YAML) |
| GET /orders/:id state machine PENDING→PROCESSING→COMPLETED | `test_orders_lifecycle.py::test_order_transitions_pending_to_processing_to_completed` |
| GET is read-only (no self-mutation) | `test_orders_lifecycle.py::test_get_order_does_not_itself_mutate_state` |
| GET unknown order → 404 / auth enforced | `test_get_nonexistent_order_returns_404`, `test_get_order_without_auth_returns_401` |
| DELETE cancels during PENDING | `test_cancel_order_while_pending_succeeds` |
| DELETE cancels during PROCESSING | `test_cancel_order_while_processing_succeeds` |
| DELETE → 409 once COMPLETED | `test_cancel_order_after_completed_returns_409` |
| Cancel-twice / cancel-unknown / cancelled-stays-cancelled | `test_cancelling_twice_is_idempotent`, `test_cancel_nonexistent_order_returns_404`, `test_cancelled_order_never_advances_state` |
| POST /exports → 202 + jobId | `test_exports.py::test_export_fast_paths[create_export_returns_job]` (YAML: `testcases/exports.yaml`) |
| Exports auth-protected | `test_create_export_without_auth_returns_401`, `test_export_status_and_download_require_auth` |
| GET /exports/:jobId PROCESSING → COMPLETED (~60s) | `test_export_completes_and_download_returns_valid_csv` (covers both the transition and the resulting download in one real-time wait) |
| Download 400 while incomplete | `test_export_fast_paths[download_before_completion_rejected]` |
| Download 200 + text/csv + payload once complete | `test_export_completes_and_download_returns_valid_csv` |
| Unknown jobId → 404 (status & download) | `test_export_fast_paths[status_for_unknown_job_is_404\|download_for_unknown_job_is_404]` |

## Assumptions

- The mock server's timing constants (5s/15s/60s) are measured from resource-creation time
  (confirmed directly in source).
- No rate limiting or concurrency limits are assumed or tested, since the server implements none.
- CSV content assertions check structure (header row, column names, `Content-Type`), not specific
  order data, because the server's CSV payload is static/hardcoded regardless of what orders exist.

## Markers / tags

`smoke`, `orders`, `exports`, `auth`, `api`, `regression`, `validation`, `boundary`, `happy`,
`invariant`, `property`, `slow` (real async waits, ~15-75s). Tags on YAML cases become these markers
automatically via `utilities/data_loader.py`. Use `--incl_tests=<tag>` / `--excl_tests=<tag>`
(added by `plugins/report_plugin.py`) or plain `pytest -m <marker>` — both work.
