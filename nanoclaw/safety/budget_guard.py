"""BudgetGuard — daily budget cap with warning threshold."""
import logging
from typing import Optional

from memory.cost_tracker import CostTracker

logger = logging.getLogger("nanoclaw.safety.budget_guard")


class BudgetGuard:
    """Enforces a daily USD spending limit on LLM calls.

    warn_at_percent: fractional value (0.0–1.0), e.g. 0.80 for 80%.
    Matches settings.budget.warn_at_percent.
    """

    def __init__(self, cost_tracker: CostTracker,
                 daily_limit_usd: float,
                 warn_at_percent: float = 0.80,
                 on_warning: Optional[callable] = None):
        self.tracker = cost_tracker
        self.limit = daily_limit_usd
        self.warn_threshold = daily_limit_usd * warn_at_percent
        self._on_warning = on_warning
        self._warning_sent_today = False

    async def check(self) -> tuple[bool, str]:
        """Returns (allowed, message).

        allowed=False if daily spend >= limit.
        Returns warning message if spend >= warn_threshold (first time only per day).
        """
        daily = await self.tracker.daily_total()

        if daily >= self.limit:
            msg = (
                f"Daily budget limit reached (${daily:.2f} / ${self.limit:.2f}). "
                f"LLM calls blocked until tomorrow."
            )
            logger.warning(msg)
            return False, msg

        if daily >= self.warn_threshold and not self._warning_sent_today:
            self._warning_sent_today = True
            pct = (daily / self.limit) * 100
            msg = (
                f"Budget warning: ${daily:.2f} / ${self.limit:.2f} "
                f"({pct:.0f}%) spent today."
            )
            logger.warning(msg)
            if self._on_warning:
                try:
                    await self._on_warning(msg)
                except Exception:
                    pass
            return True, msg

        return True, ""

    def reset_daily_warning(self) -> None:
        """Call at start of each day to re-enable warning."""
        self._warning_sent_today = False

    @property
    def is_warning_sent(self) -> bool:
        return self._warning_sent_today
