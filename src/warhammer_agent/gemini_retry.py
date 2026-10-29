"""Bounded retry for short Gemini per-minute rate limits."""

import re
import time
from collections.abc import Callable
from typing import Any

MAX_RETRY_WAIT_SECONDS = 90.0
RETRY_BUFFER_SECONDS = 1.0


def retry_after_seconds(error: Exception) -> float | None:
    if getattr(error, "code", None) != 429:
        return None
    message = str(getattr(error, "message", error))
    match = re.search(r"please retry in\s+([0-9hms.]+)", message, re.IGNORECASE)
    if not match:
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|[hms])", match.group(1))
    if not parts:
        return None
    factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(value) * factors[unit] for value, unit in parts)


def generate_content_with_retry(
    client: Any,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_wait_seconds: float = MAX_RETRY_WAIT_SECONDS,
    **request: Any,
) -> Any:
    """Retry one short 429 once; never wait through daily quota exhaustion."""
    try:
        return client.models.generate_content(**request)
    except Exception as error:
        delay = retry_after_seconds(error)
        if delay is None or delay > max_wait_seconds:
            raise
        sleep(delay + RETRY_BUFFER_SECONDS)
        return client.models.generate_content(**request)
