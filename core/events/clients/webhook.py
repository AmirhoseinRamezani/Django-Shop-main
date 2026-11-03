from __future__ import annotations

import requests


class WebhookClient:
    """Small HTTP transport for outbound webhook delivery."""

    DEFAULT_TIMEOUT = 5

    def __init__(self, endpoint: str, timeout: int | float | None = None):
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("A webhook endpoint is required.")
        self.endpoint = endpoint
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or self.timeout <= 0
        ):
            raise ValueError("Webhook timeout must be a positive number.")
        self.session = requests.Session()

    def post(
        self,
        payload: dict,
        topic: str,
        *,
        event_id: str | None = None,
    ):
        headers = {"X-Event-Topic": topic}
        if event_id:
            headers["Idempotency-Key"] = event_id

        try:
            response = self.session.post(
                self.endpoint,
                json={
                    "topic": topic,
                    "payload": payload,
                },
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response
        finally:
            self.session.close()