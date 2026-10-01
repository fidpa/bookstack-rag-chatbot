"""Runs webhook syncs after the response, in order, and retries them.

BookStack sends `page_create`, `chapter_create`, `book_create`, `page_move`,
`chapter_move` and `book_sort` from inside the database transaction that makes the
change (and, with its default queue, before it answers the editor's request). A sync
that reads BookStack back while the request is still being handled sees the state from
before the commit: a new page is still a draft, a new chapter does not exist yet. So
the endpoint only queues the work; this worker runs it a moment later and tries again
while the item is not visible yet, or while BookStack does not answer.

One thread runs the jobs one after the other, so events are applied in the order they
are due and never write to the index in parallel.
"""

import heapq
import itertools
import logging
import threading
import time
from typing import Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class QueueFull(Exception):
    """Too many jobs are waiting. BookStack does not retry a refused webhook, so the
    event is lost until the next full resync."""


class GiveUp(Exception):
    """Raised by a task that will not succeed on a later attempt either; the message
    says why. The job is dropped without using its remaining retries."""


class _Job:
    def __init__(
        self, label: str, task: Callable[[], bool], retry_delays: Sequence[float]
    ):
        self.label = label
        self.task = task
        self.retry_delays = list(retry_delays)
        self.attempts = 0


class WebhookWorker:
    """A single background thread that runs due jobs and re-queues failed ones."""

    def __init__(self, max_pending: int = 500) -> None:
        self._max_pending = max_pending
        self._cv = threading.Condition()
        self._heap: List[Tuple[float, int, _Job]] = []
        self._sequence = itertools.count()
        self._thread: Optional[threading.Thread] = None
        self._pending = 0

    def submit(
        self,
        label: str,
        task: Callable[[], bool],
        delay: float,
        retry_delays: Sequence[float],
    ) -> None:
        """
        Run `task` after `delay` seconds.

        `task` returns True when it is done. If it returns False (or raises), it is
        run again after each of `retry_delays`, and given up on after the last one.
        A task that raises GiveUp is dropped at once.

        Raises:
            QueueFull: if `max_pending` jobs are already waiting or running.
        """
        job = _Job(label, task, retry_delays)
        with self._cv:
            if self._pending >= self._max_pending:
                raise QueueFull(f"{self._pending} webhook jobs are pending")
            self._pending += 1
            self._push(job, delay)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="webhook-worker", daemon=True
                )
                self._thread.start()

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Wait until nothing is queued or running (used by tests)."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
            return True

    @property
    def pending(self) -> int:
        with self._cv:
            return self._pending

    def _push(self, job: _Job, delay: float) -> None:
        heapq.heappush(
            self._heap, (time.monotonic() + delay, next(self._sequence), job)
        )
        self._cv.notify_all()

    def _next_due(self) -> _Job:
        with self._cv:
            while True:
                if self._heap:
                    wait = self._heap[0][0] - time.monotonic()
                    if wait <= 0:
                        return heapq.heappop(self._heap)[2]
                    self._cv.wait(wait)
                else:
                    self._cv.wait()

    def _run(self) -> None:
        while True:
            job = self._next_due()
            job.attempts += 1
            try:
                done = bool(job.task())
            except GiveUp as e:
                logger.warning(f"Webhook job {job.label} gave up: {e}")
                with self._cv:
                    self._pending -= 1
                    self._cv.notify_all()
                continue
            except Exception:
                logger.error(f"Webhook job {job.label} failed", exc_info=True)
                done = False

            with self._cv:
                if done:
                    logger.info(f"Webhook job {job.label} done after {job.attempts}")
                elif job.retry_delays:
                    logger.info(
                        f"Webhook job {job.label} not done after {job.attempts}, retrying"
                    )
                    self._push(job, job.retry_delays.pop(0))
                    continue
                else:
                    plural = "s" if job.attempts > 1 else ""
                    logger.warning(
                        f"Webhook job {job.label} gave up after {job.attempts} "
                        f"attempt{plural}: "
                        "the API token cannot see the item (restricted, "
                        "or deleted meanwhile) or BookStack is unreachable. If it "
                        "belongs in the index, run resync.py --full-resync"
                    )
                self._pending -= 1
                self._cv.notify_all()
