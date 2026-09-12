import os


class Config:
    """All environment-tunable settings. Nothing here is hardcoded elsewhere
    in the framework -- clients and tests read exclusively through this object."""

    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:3000/v1")
    REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))

    # Polling defaults tuned to the mock server's CONFIRMED timings (read directly
    # from server.js): orders PENDING->PROCESSING at 5s, PROCESSING->COMPLETED at
    # 15s (both measured from order creation); exports PROCESSING->COMPLETED at
    # 60s. Timeouts include headroom for CI scheduling jitter.
    ORDER_POLL_INTERVAL = float(os.getenv("ORDER_POLL_INTERVAL_SECONDS", "1"))
    ORDER_POLL_TIMEOUT = float(os.getenv("ORDER_POLL_TIMEOUT_SECONDS", "25"))

    EXPORT_POLL_INTERVAL = float(os.getenv("EXPORT_POLL_INTERVAL_SECONDS", "2"))
    EXPORT_POLL_TIMEOUT = float(os.getenv("EXPORT_POLL_TIMEOUT_SECONDS", "75"))


config = Config()
