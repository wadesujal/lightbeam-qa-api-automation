"""Fast export cases are YAML-driven; the full lifecycle (real ~60s wait +
download) is a direct test, same rationale as test_orders_lifecycle.py."""

import pytest

from utilities.api_client import ExportClient
from utilities.data_loader import load_cases
from utilities.polling import wait_for_condition
from utilities.soft_assert import SoftAssert

CASES = load_cases("exports.yaml")


@pytest.mark.exports
@pytest.mark.parametrize("case", CASES)
def test_export_fast_paths(export_client, case, step_log):
    sa = SoftAssert(step_log)
    exp = case["expected"]

    if case["id"] == "create_export_returns_job":
        with step_log.step("POST /exports"):
            response = export_client.create_export()
        sa.equals(response.status_code, exp["status"], "status code")
        body = response.json()
        sa.check(bool(body.get("jobId")), "jobId present")
        sa.equals(body.get("status"), exp["job_status"], "initial job status")

    elif case["id"] == "download_before_completion_rejected":
        job_id = export_client.create_export().json()["jobId"]
        with step_log.step("GET download while still PROCESSING"):
            response = export_client.download(job_id)
        sa.equals(response.status_code, exp["download_status_while_processing"], "status code")

    elif case["id"] == "status_for_unknown_job_is_404":
        with step_log.step("GET status for unknown jobId"):
            response = export_client.get_status("JOB-99999999")
        sa.equals(response.status_code, exp["unknown_job_status_code"], "status code")

    elif case["id"] == "download_for_unknown_job_is_404":
        with step_log.step("GET download for unknown jobId"):
            response = export_client.download("JOB-99999999")
        sa.equals(response.status_code, exp["unknown_job_download_status_code"], "status code")

    sa.assert_all()


@pytest.mark.exports
def test_create_export_without_auth_returns_401(settings):
    client = ExportClient(settings=settings, token=None)
    response = client.create_export()
    assert response.status_code == 401, response.text


@pytest.mark.exports
def test_export_status_and_download_require_auth(settings):
    client = ExportClient(settings=settings, token=None)
    assert client.get_status("JOB-00000").status_code == 401
    assert client.download("JOB-00000").status_code == 401


@pytest.mark.exports
@pytest.mark.slow
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

    lines = response.text.strip().splitlines()
    sa.check(len(lines) >= 2, "CSV has a header row plus at least one data row")
    if lines:
        sa.equals(lines[0].split(","), ["orderId", "status", "totalAmount"], "CSV header")

    sa.assert_all()
