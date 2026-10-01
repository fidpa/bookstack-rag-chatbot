"""The worker that runs webhook syncs after the response."""

import time

import pytest

from bookstack.webhook_worker import GiveUp, QueueFull, WebhookWorker


@pytest.fixture
def worker():
    worker = WebhookWorker()
    yield worker
    assert worker.wait_idle(5)


def test_jobs_run_in_the_order_they_were_submitted(worker):
    ran = []
    for name in ("first", "second", "third"):
        worker.submit(name, lambda name=name: ran.append(name) or True, 0.0, ())
    assert worker.wait_idle(5)
    assert ran == ["first", "second", "third"]


def test_a_job_waits_for_its_delay(worker):
    started = time.monotonic()
    ran = []
    worker.submit(
        "late", lambda: ran.append(time.monotonic() - started) or True, 0.2, ()
    )
    assert worker.wait_idle(5)
    assert ran[0] >= 0.19


def test_an_earlier_due_job_overtakes_a_later_one(worker):
    ran = []
    worker.submit("slow", lambda: ran.append("slow") or True, 0.15, ())
    worker.submit("quick", lambda: ran.append("quick") or True, 0.0, ())
    assert worker.wait_idle(5)
    assert ran == ["quick", "slow"]


def test_a_job_that_is_not_done_is_retried_until_it_is(worker):
    attempts = []

    def task():
        attempts.append(1)
        return len(attempts) == 3

    worker.submit("flaky", task, 0.0, (0.01, 0.01, 0.01))
    assert worker.wait_idle(5)
    assert len(attempts) == 3


def test_it_gives_up_after_the_last_retry_delay(worker, caplog):
    attempts = []
    worker.submit("hopeless", lambda: attempts.append(1) or False, 0.0, (0.01, 0.01))
    assert worker.wait_idle(5)
    assert len(attempts) == 3
    assert "gave up after 3 attempts" in caplog.text


def test_a_task_that_gives_up_is_not_retried(worker, caplog):
    attempts = []

    def task():
        attempts.append(1)
        raise GiveUp("the item is gone")

    worker.submit("gone", task, 0.0, (0.01, 0.01))
    started = time.monotonic()
    assert worker.wait_idle(5)
    assert time.monotonic() - started < 1, "wait_idle was not woken up"
    assert len(attempts) == 1
    assert "gave up: the item is gone" in caplog.text


def test_an_exception_counts_as_not_done_and_does_not_stop_the_worker(worker):
    attempts = []

    def task():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("BookStack is restarting")
        return True

    ran = []
    worker.submit("raises", task, 0.0, (0.01,))
    worker.submit("after", lambda: ran.append(1) or True, 0.05, ())
    assert worker.wait_idle(5)
    assert len(attempts) == 2 and ran == [1]


def test_wait_idle_times_out_while_a_job_is_pending(worker):
    worker.submit("far away", lambda: True, 30.0, ())
    assert worker.wait_idle(0.05) is False
    assert worker.pending == 1
    # let the fixture finish quickly: replace the far job by draining it
    worker._heap.clear()
    with worker._cv:
        worker._pending = 0
        worker._cv.notify_all()


def test_a_full_queue_refuses_more_jobs_instead_of_growing():
    worker = WebhookWorker(max_pending=2)
    worker.submit("one", lambda: True, 30.0, ())
    worker.submit("two", lambda: True, 30.0, ())
    with pytest.raises(QueueFull):
        worker.submit("three", lambda: True, 0.0, ())
    assert worker.pending == 2


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_dead_worker_thread_is_replaced_on_the_next_submit(worker):
    # The thread is a daemon started on the first submit; if it ever ends, the
    # next event must start a new one rather than queue into nothing.
    def fatal():
        raise SystemExit  # not an Exception, so it ends the thread

    worker.submit("fatal", fatal, 0.0, ())
    dead = worker._thread
    dead.join(5)
    assert not dead.is_alive()
    with worker._cv:
        worker._pending -= 1  # the job that ended the thread never finished

    ran = []
    worker.submit("second", lambda: ran.append(1) or True, 0.0, ())
    assert worker.wait_idle(5)
    assert ran == [1]
