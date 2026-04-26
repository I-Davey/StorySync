from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import processor


class _ExecuteResult:
    def __init__(self, *, one=None, many=None, rowcount: int = 0):
        self._one = one
        self._many = many or []
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return SimpleNamespace(all=lambda: self._many)


class _FakeDB:
    def __init__(self, results: list[_ExecuteResult]):
        self._results = list(results)
        self.commits = 0
        self.refresh_calls = []

    def execute(self, _stmt):
        if not self._results:
            return _ExecuteResult()
        return self._results.pop(0)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refresh_calls.append(obj)


def test_claim_next_job_sets_processing_and_lease(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        state="queued",
        worker_id=None,
        lease_expires_at=None,
        attempt_count=0,
        queue_position=9,
        created_at=datetime.now(timezone.utc),
    )
    db = _FakeDB([_ExecuteResult(one=job)])

    monkeypatch.setattr("app.services.processor.settings.processor_lease_seconds", 30)

    claimed = processor.claim_next_job(db, worker_id="w1", now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert claimed is job
    assert job.state == "processing"
    assert job.worker_id == "w1"
    assert job.queue_position is None
    assert job.attempt_count == 1
    assert db.commits == 1
    assert db.refresh_calls == [job]


def test_recover_expired_leases_requeues_jobs(monkeypatch) -> None:
    jobs = [
        SimpleNamespace(state="processing", queue_position=None, worker_id="a", lease_expires_at=datetime.now(timezone.utc), last_error=None),
        SimpleNamespace(state="processing", queue_position=None, worker_id="b", lease_expires_at=datetime.now(timezone.utc), last_error="old"),
    ]
    db = _FakeDB([_ExecuteResult(many=jobs)])
    positions = iter([101, 102])
    monkeypatch.setattr("app.services.processor._next_queue_position", lambda _db: next(positions))

    count = processor.recover_expired_leases(db, now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert count == 2
    assert jobs[0].state == "queued"
    assert jobs[0].queue_position == 101
    assert jobs[0].worker_id is None
    assert jobs[1].queue_position == 102
    assert "Lease expired" in jobs[1].last_error
    assert db.commits == 1


def test_heartbeat_job_returns_true_on_row_update() -> None:
    db = _FakeDB([_ExecuteResult(rowcount=1)])

    ok = processor.heartbeat_job(db, uuid.uuid4(), "w1")

    assert ok
    assert db.commits == 1


def test_complete_job_failure_requeues_when_retryable(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        state="processing",
        worker_id="w1",
        attempt_count=1,
        queue_position=None,
        lease_expires_at=datetime.now(timezone.utc),
        last_error=None,
    )
    db = _FakeDB([_ExecuteResult(one=job)])
    monkeypatch.setattr("app.services.processor.settings.processor_max_attempts", 3)
    monkeypatch.setattr("app.services.processor._next_queue_position", lambda _db: 55)

    ok = processor.complete_job_failure(db, job.id, "w1", "boom", retryable=True)

    assert ok
    assert job.state == "queued"
    assert job.queue_position == 55
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.last_error == "boom"
    assert db.commits == 1


def test_complete_job_failure_marks_failed_when_attempts_exhausted(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        state="processing",
        worker_id="w1",
        attempt_count=3,
        queue_position=7,
        lease_expires_at=datetime.now(timezone.utc),
        last_error=None,
    )
    db = _FakeDB([_ExecuteResult(one=job)])
    monkeypatch.setattr("app.services.processor.settings.processor_max_attempts", 3)

    ok = processor.complete_job_failure(db, job.id, "w1", "fatal", retryable=True)

    assert ok
    assert job.state == "failed"
    assert job.queue_position is None
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.last_error == "fatal"
    assert db.commits == 1
