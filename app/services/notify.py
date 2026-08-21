"""Webhook notifications — generic JSON, Discord, and ntfy."""

import logging
from typing import Tuple

import httpx

logger = logging.getLogger(__name__)


class Notifier:
    TIMEOUT = 10

    def send(self, title: str, message: str, cfg) -> Tuple[bool, str]:
        if not cfg.notify_enabled:
            return False, "disabled"
        if not cfg.notify_url:
            return False, "no URL configured"

        try:
            if cfg.notify_type == "discord":
                payload = self.build_payload("discord", title, message)
                r = httpx.post(cfg.notify_url, json=payload, timeout=self.TIMEOUT)
            elif cfg.notify_type == "ntfy":
                body = self.build_payload("ntfy", title, message)
                r = httpx.post(
                    cfg.notify_url,
                    content=body.encode("utf-8"),
                    headers={"Title": title},
                    timeout=self.TIMEOUT,
                )
            else:
                payload = self.build_payload("generic", title, message)
                r = httpx.post(cfg.notify_url, json=payload, timeout=self.TIMEOUT)

            r.raise_for_status()
            return True, f"sent ({r.status_code})"
        except Exception as e:
            logger.warning("Notification failed: %s", e)
            return False, str(e)

    @staticmethod
    def build_payload(notify_type: str, title: str, message: str):
        """Pure helper — returns the exact body sent for each channel."""
        if notify_type == "discord":
            content = f"**{title}**\n{message}"
            return {"content": content[:2000]}  # Discord hard limit
        if notify_type == "ntfy":
            return message
        return {"title": title, "message": message}
