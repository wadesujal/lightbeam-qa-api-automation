import pytest

from config.config import config
from src.clients.export_client import ExportClient
from src.utils.polling import wait_for_condition


pytestmark = pytest.mark.exports


class TestCreateExport:
    @pytest.mark.smoke
    def test_create_export_returns_202_with_job_id(self, export_client):
        response = export_client.create_export()
        assert response.status_code == 202, response.text
        body = response.json()
        assert body.get("jobId"), f"Expected a non-empty jobId, got: {body}"
        assert body["status"] == "PROCESSING"

    def test_create_export_without_auth_returns_401(self):
        client = ExportClient(token=None)
        response = client.create_export()
        assert response.status_code == 401, response.text


class TestExportStatus:
    def test_status_is_processing_immediately_after_creation(self, export_client):
        job_id = export_client.create_export().json()["jobId"]
        response = export_client.get_status(job_id)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "PROCESSING"

    @pytest.mark.smoke
    def test_status_for_nonexistent_job_returns_404(self, export_client):
        response = export_client.get_status("JOB-99999999")
        assert response.status_code == 404, response.text

    def test_status_without_auth_returns_401(self):
        client = ExportClient(token=None)
        response = client.get_status("JOB-00000")
        assert response.status_code == 401, response.text


class TestDownloadExport:
    @pytest.mark.smoke
    def test_download_before_completion_returns_400(self, export_client):
        job_id = export_client.create_export().json()["jobId"]
        response = export_client.download(job_id)
        assert response.status_code == 400, response.text

    def test_download_for_nonexistent_job_returns_404(self, export_client):
        response = export_client.download("JOB-99999999")
        assert response.status_code == 404, response.text

    def test_download_without_auth_returns_401(self):
        client = ExportClient(token=None)
        response = client.download("JOB-00000")
        assert response.status_code == 401, response.text

    @pytest.mark.slow
    def test_export_completes_and_download_returns_valid_csv(self, export_client):
        job_id = export_client.create_export().json()["jobId"]

        result = wait_for_condition(
            poll_fn=lambda: export_client.get_status(job_id).json(),
            predicate=lambda j: j["status"] == "COMPLETED",
            timeout=config.EXPORT_POLL_TIMEOUT,
            interval=config.EXPORT_POLL_INTERVAL,
            description=f"export job {job_id} to reach COMPLETED",
        )
        assert result.value.get("downloadUrl"), "Completed job should expose a downloadUrl"

        response = export_client.download(job_id)
        assert response.status_code == 200, response.text
        assert "text/csv" in response.headers.get("Content-Type", ""), response.headers

        lines = response.text.strip().splitlines()
        assert len(lines) >= 2, f"Expected a header row plus at least one data row, got: {response.text!r}"
        assert lines[0].split(",") == ["orderId", "status", "totalAmount"], f"Unexpected CSV header: {lines[0]}"
