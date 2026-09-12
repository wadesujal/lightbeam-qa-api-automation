"""Export job coverage.

Fast cases are YAML-driven; the full lifecycle (real ~60s wait + download)
is a direct test, same rationale as test_orders_lifecycle.py.

The YAML cases here carry the expected status codes and the tags, while the
interaction each one needs (create-then-download, fetch-unknown-id, ...) is a
named handler below. The handlers are resolved through an explicit registry
rather than an if/elif chain so that a YAML case with no matching handler
*fails loudly* instead of running zero assertions and reporting green.
"""

import pytest

from utilities.data_loader import load_cases
from utilities.polling import wait_for_condition
from utilities.soft_assert import SoftAssert

CASES = load_cases("exports.yaml")


def _create_export_returns_job(export_client, exp, step_log, sa):
    with step_log.step("POST /exports"):
        response = export_client.create_export()
    sa.equals(response.status_code, exp["status"], "status code")
    body = response.json()
    sa.check(bool(body.get("jobId")), "jobId present")
    sa.equals(body.get("status"), exp["job_status"], "initial job status")
    # The server advertises how often to poll; a client that ignores it either
    # hammers the endpoint or waits too long, so it is part of the contract.
    sa.equals(body.get("pollIntervalSeconds"), exp["poll_interval_seconds"], "pollIntervalSeconds")


def _download_before_completion_rejected(export_client, exp, step_log, sa):
    job_id = export_client.create_export().json()["jobId"]
    with step_log.step("GET download while still PROCESSING"):
        response = export_client.download(job_id)
    sa.equals(response.status_code, exp["status"], "status code")
    sa.check("error" in response.json(), "error field present")


def _status_while_processing(export_client, exp, step_log, sa):
    job_id = export_client.create_export().json()["jobId"]
    with step_log.step("GET status while still PROCESSING"):
        response = export_client.get_status(job_id)
    sa.equals(response.status_code, exp["status"], "status code")
    body = response.json()
    sa.equals(body.get("jobId"), job_id, "jobId echoed")
    sa.equals(body.get("status"), exp["job_status"], "job still PROCESSING")
    # An in-flight job must not hand out a download link -- that is what makes
    # the 400-on-early-download path reachable in the first place.
    sa.check(body.get("downloadUrl") is None, "no downloadUrl while incomplete")


def _status_for_unknown_job(export_client, exp, step_log, sa):
    with step_log.step("GET status for unknown jobId"):
        response = export_client.get_status("JOB-99999999")
    sa.equals(response.status_code, exp["status"], "status code")


def _download_for_unknown_job(export_client, exp, step_log, sa):
    with step_log.step("GET download for unknown jobId"):
        response = export_client.download("JOB-99999999")
    sa.equals(response.status_code, exp["status"], "status code")


CASE_HANDLERS = {
    "create_export_returns_job": _create_export_returns_job,
    "download_before_completion_rejected": _download_before_completion_rejected,
    "status_while_processing_has_no_download_url": _status_while_processing,
    "status_for_unknown_job_is_404": _status_for_unknown_job,
    "download_for_unknown_job_is_404": _download_for_unknown_job,
}


@pytest.mark.exports
@pytest.mark.parametrize("case", CASES)
def test_export_fast_paths(export_client, case, step_log):
    handler = CASE_HANDLERS.get(case["id"])
    if handler is None:
        pytest.fail(
            f"No handler registered for exports.yaml case {case['id']!r}. "
            f"Add one to CASE_HANDLERS -- an unhandled case would otherwise "
            f"assert nothing and report as passed."
        )

    sa = SoftAssert(step_log)
    handler(export_client, case["expected"], step_log, sa)
    sa.assert_all()


@pytest.mark.exports
@pytest.mark.title(
    "Validate that the exports API returns 401 for an unauthenticated create request"
)
def test_create_export_without_auth_returns_401(anonymous_export_client):
    response = anonymous_export_client.create_export()
    assert response.status_code == 401, response.text


@pytest.mark.exports
@pytest.mark.title(
    "Validate that the export status and download APIs return 401 without authentication"
)
def test_export_status_and_download_require_auth(anonymous_export_client):
    status = anonymous_export_client.get_status("JOB-00000")
    download = anonymous_export_client.download("JOB-00000")
    assert status.status_code == 401, status.text
    assert download.status_code == 401, download.text


@pytest.mark.exports
@pytest.mark.slow
@pytest.mark.title(
    "Validate that an export completes after ~60s and downloads a valid CSV payload"
)
def test_export_completes_and_download_returns_valid_csv(export_client, settings, step_log):
    sa = SoftAssert(step_log)
    job_id = export_client.create_export().json()["jobId"]

    with step_log.step("wait for export COMPLETED (~60s)"):
        result = wait_for_condition(
            poll_fn=lambda: export_client.get_status(job_id).json(),
            predicate=lambda j: j["status"] == "COMPLETED",
            timeout=settings.export_poll_timeout_seconds,
            interval=settings.export_poll_interval_seconds,
            description=f"export job {job_id} to reach COMPLETED",
        )
    sa.check(bool(result.value.get("downloadUrl")), "completed job exposes a downloadUrl")

    with step_log.step("GET download once COMPLETED"):
        response = export_client.download(job_id)

    sa.equals(response.status_code, 200, "status code")
    sa.check("text/csv" in response.headers.get("Content-Type", ""), "Content-Type is text/csv")
    # A CSV export is meant to be saved, not rendered -- the attachment
    # disposition and filename are part of that contract.
    disposition = response.headers.get("Content-Disposition", "")
    sa.check("attachment" in disposition, "response is served as an attachment")
    sa.check(".csv" in disposition, "attachment filename is a .csv")

    lines = response.text.strip().splitlines()
    sa.check(len(lines) >= 2, "CSV has a header row plus at least one data row")
    if lines:
        header = lines[0].split(",")
        sa.equals(header, ["orderId", "status", "totalAmount"], "CSV header")
        # Every data row must line up with the header -- a ragged CSV is the
        # classic silent export bug.
        ragged = [row for row in lines[1:] if len(row.split(",")) != len(header)]
        sa.check(not ragged, f"every data row has {len(header)} columns (ragged rows: {ragged})")

    sa.assert_all()
