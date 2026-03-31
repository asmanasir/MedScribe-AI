"""
Webhook integration — notify external systems when things happen.

When a note is approved, the EPJ system needs to know. Instead of the EPJ polling
your /status endpoint, you push a webhook to their callback URL.

Security:
- Webhooks are signed with HMAC-SHA256 using a shared secret
- The receiver verifies the signature to prove the webhook is authentic
- This prevents spoofing (someone pretending to be your system)

This module is an event handler — it subscribes to events and
sends webhooks when they fire.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import structlog

from medscribe.config import Settings
from medscribe.integration.events import Event

logger = structlog.get_logger()


class WebhookSender:
    """
    Sends signed webhooks to external systems.

    Usage:
        sender = WebhookSender(settings)
        bus.subscribe("visit.approved", sender.handle_event)
    """

    def __init__(self, settings: Settings) -> None:
        self._url = settings.webhook_url
        self._secret = settings.webhook_secret.get_secret_value()
        self._client = httpx.AsyncClient(timeout=10.0)

    async def handle_event(self, event: Event) -> None:
        """Event handler — sends webhook for any subscribed event."""
        if not self._url:
            return

        payload = {
            "event": event.event_type,
            "event_id": str(event.event_id),
            "visit_id": str(event.visit_id) if event.visit_id else None,
            "data": event.data,
            "timestamp": event.timestamp.isoformat(),
        }

        body = json.dumps(payload, default=str)
        signature = self._sign(body)

        try:
            response = await self._client.post(
                self._url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-MedScribe-Signature": signature,
                    "X-MedScribe-Event": event.event_type,
                },
            )
            logger.info(
                "webhook.sent",
                event_type=event.event_type,
                status_code=response.status_code,
                url=self._url,
            )
        except httpx.HTTPError as e:
            logger.error(
                "webhook.failed",
                event_type=event.event_type,
                url=self._url,
                error=str(e),
            )

    def _sign(self, body: str) -> str:
        """Create HMAC-SHA256 signature for webhook verification."""
        return hmac.new(
            self._secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
