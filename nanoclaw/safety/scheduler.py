"""DailyScheduler — posts daily report at configured time."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable

logger = logging.getLogger("nanoclaw.safety.scheduler")


class DailyScheduler:
    """Runs an async callback once per day at a configured time.

    report_time: "HH:MM" string from settings.budget.daily_report_time.
    Uses local system time (no timezone config needed for a single-machine bot).
    """

    def __init__(self, report_time: str,
                 callback: Callable[[], Awaitable],
                 on_day_reset: Callable[[], None] | None = None):
        self.hour, self.minute = map(int, report_time.split(":"))
        self.callback = callback
        self._on_day_reset = on_day_reset
        self._stop = False

    async def run(self) -> None:
        """Run forever, firing callback once per day at configured time."""
        logger.info(
            "DailyScheduler started — reports at %02d:%02d local time",
            self.hour, self.minute,
        )
        while not self._stop:
            await self._sleep_until_next()
            if self._stop:
                break
            try:
                logger.info("Firing daily report callback")
                await self.callback()
            except Exception as e:
                logger.error("Daily report callback failed: %s", e)

            # Reset daily state (e.g. budget warning flag)
            if self._on_day_reset:
                try:
                    self._on_day_reset()
                except Exception:
                    pass

    async def _sleep_until_next(self) -> None:
        """Sleep until the next occurrence of the configured time."""
        now = datetime.now()
        target = now.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        logger.debug("Sleeping %.0f seconds until next report", wait_seconds)

        # Sleep in small increments so stop signal is responsive
        while wait_seconds > 0 and not self._stop:
            chunk = min(wait_seconds, 30.0)
            await asyncio.sleep(chunk)
            wait_seconds -= chunk

    async def stop(self) -> None:
        """Signal the scheduler to stop."""
        self._stop = True
        logger.info("DailyScheduler stop requested")
