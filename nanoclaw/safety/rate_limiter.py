"""RateLimiter — per-operation sliding window rate limits with cooldown."""
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("nanoclaw.safety.rate_limiter")


class RateLimiter:
    """Sliding-window rate limiter.

    limits dict maps operation names to max calls per hour:
        {"llm_calls_per_hour": 30, "claude_code_per_hour": 10, ...}

    cooldown_minutes: after hitting a limit, all operations of that type
    are blocked for this many minutes (prevents rapid retry storms).
    """

    def __init__(self, limits: dict[str, int],
                 cooldown_minutes: int = 10):
        self._limits = limits
        self._cooldown = timedelta(minutes=cooldown_minutes)
        self._windows: dict[str, deque[datetime]] = defaultdict(deque)
        self._cooldown_until: dict[str, datetime] = {}

    def check(self, operation: str) -> tuple[bool, str]:
        """Returns (allowed, reason). allowed=False if rate limit exceeded."""
        now = datetime.now(timezone.utc)

        # Check cooldown first
        cooldown_end = self._cooldown_until.get(operation)
        if cooldown_end and now < cooldown_end:
            remaining = int((cooldown_end - now).total_seconds() / 60) + 1
            return False, (
                f"Rate limit cooldown active for `{operation}`. "
                f"Try again in ~{remaining} min."
            )

        limit_key = self._resolve_limit_key(operation)
        if not limit_key:
            return True, ""

        limit = self._limits[limit_key]
        window = self._windows[operation]

        # Prune entries older than 1 hour
        cutoff = now - timedelta(hours=1)
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= limit:
            # Enter cooldown
            self._cooldown_until[operation] = now + self._cooldown
            logger.warning(
                "Rate limit hit for %s (%d/%d per hour). "
                "Cooldown for %d minutes.",
                operation, len(window), limit,
                int(self._cooldown.total_seconds() / 60),
            )
            return False, (
                f"Rate limit reached for `{operation}` "
                f"({len(window)}/{limit} per hour). "
                f"Cooling down for {int(self._cooldown.total_seconds() / 60)} min."
            )

        return True, ""

    def record(self, operation: str) -> None:
        """Record that an operation was performed now."""
        self._windows[operation].append(datetime.now(timezone.utc))

    def get_usage(self, operation: str) -> dict:
        """Return current usage stats for an operation."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=1)
        window = self._windows.get(operation, deque())

        # Prune stale
        while window and window[0] < cutoff:
            window.popleft()

        limit_key = self._resolve_limit_key(operation)
        limit = self._limits.get(limit_key, 0) if limit_key else 0

        return {
            "operation": operation,
            "used": len(window),
            "limit": limit,
            "in_cooldown": bool(
                self._cooldown_until.get(operation)
                and now < self._cooldown_until[operation]
            ),
        }

    def reset(self, operation: str) -> None:
        """Clear rate limit state for an operation."""
        self._windows.pop(operation, None)
        self._cooldown_until.pop(operation, None)

    def _resolve_limit_key(self, operation: str) -> str | None:
        """Map operation name to its limit key in the config."""
        # Direct match
        if operation in self._limits:
            return operation

        # Try with _per_hour suffix
        key = f"{operation}_per_hour"
        if key in self._limits:
            return key

        return None
