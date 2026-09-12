from src.clients.base_client import BaseClient


class AuthClient(BaseClient):
    """Wraps POST /auth/login. Never called with a token attached -- login itself is public."""

    def login(self, username: str, api_key: str):
        return self.post("/auth/login", json_body={"username": username, "apiKey": api_key})
