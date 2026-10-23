"""Exceptions with plain-language messages shown to the user when a job stops."""

from __future__ import annotations


class ReconError(Exception):
    """Base class. ``user_message`` is safe to show in the UI (never contains secrets)."""

    user_message: str = "Unexpected error."

    def __init__(self, user_message: str | None = None) -> None:
        if user_message is not None:
            self.user_message = user_message
        super().__init__(self.user_message)


class ReadOnlyViolation(ReconError):
    """Raised when anything other than GET is attempted against the Kalshi API."""

    def __init__(self, method: str, path: str) -> None:
        super().__init__(
            f"Blocked: Kalshi Recon is read-only and refused to send {method} {path}. "
            "Only GET requests are allowed."
        )


class WsCommandBlocked(ReconError):
    """Raised when a WebSocket message other than a market-data ``subscribe`` would be sent."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"Blocked: Kalshi Recon only sends WebSocket 'subscribe' commands for market-data "
            f"channels. {detail}"
        )


class SpecViolation(ReconError):
    """Raised when a path does not match any GET operation in specs/openapi.yaml."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"Blocked: {path} is not a GET endpoint in specs/openapi.yaml, so it was not called."
        )


class AuthNotConfigured(ReconError):
    """Raised when an authenticated call is requested without credentials in .env."""

    user_message = (
        "No API key configured. Set KALSHI_KEY_ID and KALSHI_PRIVATE_KEY (or "
        "KALSHI_PRIVATE_KEY_PATH) in .env and restart the backend."
    )


class RateLimited(ReconError):
    """Raised on the first HTTP 429. Jobs stop immediately when they see this."""

    def __init__(self, path: str, cooldown_s: float) -> None:
        self.cooldown_s = cooldown_s
        super().__init__(
            f"Stopped at the first HTTP 429 (rate limited) on {path}. The client is pausing "
            f"for {cooldown_s:.0f}s before any further request. Lower the request rate in "
            "Settings and try again."
        )


class JobCancelled(ReconError):
    """Raised when the user stops a job (or presses Stop all jobs)."""

    user_message = "Stopped by user."


class RequestBudgetExceeded(ReconError):
    """Raised when a job tries to exceed its hard request cap."""

    def __init__(self, cap: int) -> None:
        super().__init__(
            f"Reached this job's request cap of {cap}. Raise the cap in the run settings if "
            "you need more."
        )
