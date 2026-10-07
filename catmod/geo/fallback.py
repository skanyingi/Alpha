"""Primary Google Cloud → open-stack fallback. Never removes Google call sites."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, TypeVar

import httpx

logger = logging.getLogger("catmod.fallback")

T = TypeVar("T")

GOOGLE_DENY_STATUSES = {
    "REQUEST_DENIED",
    "OVER_QUERY_LIMIT",
    "UNKNOWN_ERROR",
    "INVALID_REQUEST",
}


def _redact(reason: str) -> str:
    cleaned = re.sub(r"(key=)[^&\s]+", r"\1REDACTED", reason, flags=re.IGNORECASE)
    cleaned = re.sub(r"(AIza[0-9A-Za-z_-]{20,})", "REDACTED", cleaned)
    return cleaned


def log_fallback(service: str, reason: str, fallback_name: str) -> None:
    logger.warning(
        "[Fallback Mode] Google %s failed: %s. Using %s.",
        service,
        _redact(str(reason)),
        fallback_name,
    )


def google_status_reason(body: dict[str, Any] | None) -> str | None:
    if not body:
        return None
    status = str(body.get("status") or "")
    if status in GOOGLE_DENY_STATUSES or (
        status not in {"OK", "ZERO_RESULTS", ""} and status
    ):
        detail = body.get("error_message") or status or "unknown"
        return f"{status}: {detail}"
    if body.get("error"):
        return str(body["error"])
    return None


def is_billing_or_auth_failure(exc: BaseException) -> bool:
    text = str(exc).upper()
    if any(
        token in text
        for token in ("REQUEST_DENIED", "OVER_QUERY_LIMIT", "BILLING", "403", "401")
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code in {400, 401, 403, 429}
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError))


def fetch_with_fallback(
    *,
    service: str,
    primary: Callable[[], T],
    fallback: Callable[[], T],
    fallback_name: str,
) -> T:
    """Run Google primary; on timeout, HTTP 4xx, or deny status, run the open fallback."""
    try:
        return primary()
    except Exception as exc:
        log_fallback(service, str(exc) or type(exc).__name__, fallback_name)
        return fallback()
