from src.clients.base_client import BaseClient


class ExportClient(BaseClient):
    def create_export(self):
        return self.post("/exports")

    def get_status(self, job_id: str):
        return self.get(f"/exports/{job_id}")

    def download(self, job_id: str):
        return self.get(f"/exports/{job_id}/download")
