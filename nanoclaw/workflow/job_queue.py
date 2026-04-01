"""AsyncJobQueue — background execution preventing Discord timeouts."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

logger = logging.getLogger("nanoclaw.job_queue")


@dataclass
class Job:
    id: str
    fn: Callable[[], Awaitable]
    discord_thread_id: Optional[str] = None
    on_error: Optional[Callable[[Exception], Awaitable]] = None


class JobQueue:
    def __init__(self, max_concurrent: int = 2):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._stop = False
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_jobs: dict[str, Job] = {}

    async def enqueue(self, job: Job) -> None:
        """Add a job to the queue."""
        await self._queue.put(job)
        logger.info("Enqueued job %s", job.id)

    async def stop(self) -> None:
        """Signal the worker loop to stop after current jobs complete."""
        self._stop = True
        logger.info("Job queue stop requested")

    async def resume(self) -> None:
        """Resume accepting and processing jobs."""
        self._stop = False
        logger.info("Job queue resumed")

    @property
    def is_stopped(self) -> bool:
        return self._stop

    @property
    def active_count(self) -> int:
        return len(self._active_jobs)

    @property
    def queued_count(self) -> int:
        return self._queue.qsize()

    async def run(self) -> None:
        """Worker loop — call once at startup as asyncio.create_task(queue.run()).

        Uses create_task so each job runs concurrently up to max_concurrent,
        rather than awaiting sequentially.

        Note: task_done() is called inside _execute()'s finally block, so
        await queue.join() works correctly even though jobs are fire-and-forget here.
        """
        logger.info("Job queue worker started")
        while not self._stop:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if self._stop:
                self._queue.task_done()
                break
            asyncio.create_task(self._execute(job))

    async def _execute(self, job: Job) -> None:
        async with self._semaphore:
            self._active_jobs[job.id] = job
            try:
                logger.info("Executing job %s", job.id)
                await job.fn()
                logger.info("Job %s completed", job.id)
            except Exception as e:
                logger.error("Job %s failed: %s", job.id, e)
                if job.on_error:
                    try:
                        await job.on_error(e)
                    except Exception:
                        pass
            finally:
                self._active_jobs.pop(job.id, None)
                self._queue.task_done()
