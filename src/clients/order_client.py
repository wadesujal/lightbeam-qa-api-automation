import uuid

from src.clients.base_client import BaseClient


class OrderClient(BaseClient):
    def create_order(self, payload: dict, correlation_id: str = None, include_correlation_id: bool = True):
        headers = {}
        if include_correlation_id:
            headers["X-Correlation-ID"] = correlation_id or str(uuid.uuid4())
        return self.post("/orders", json_body=payload, headers=headers)

    def get_order(self, order_id: str):
        return self.get(f"/orders/{order_id}")

    def delete_order(self, order_id: str):
        return self.delete(f"/orders/{order_id}")
