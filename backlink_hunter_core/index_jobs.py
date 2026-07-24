"""Persisted job-state manager."""

from __future__ import annotations

from dataclasses import dataclass, field

from typing import Any, Dict, List, Optional

from .db import Database

from .models import JobStatus

DEFAULT_STATS: Dict[str, Any] = {

    "files_discovered": 0,

    "files_downloaded": 0,

    "bytes_downloaded": 0,

    "records_read": 0,

    "pages_parsed": 0,

    "links_extracted": 0,

    "backlinks_inserted": 0,

    "duplicates_skipped": 0,

    "malformed_records": 0,

    "failed_requests": 0,

    "retry_count": 0,

    "checkpoints_saved": 0,

}

@dataclass

class JobHandle:

    db: Database

    job_id: int

    _stats: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_STATS))

    def refresh(self) -> Dict[str, Any]:

        row = self.db.get_job(self.job_id) or {}

        if row.get("stats"):

            self._stats.update(row["stats"])

        return row

    def bump(self, key: str, amount: int = 1) -> None:

        self._stats[key] = self._stats.get(key, 0) + amount

    def set_stat(self, key: str, value: Any) -> None:

        self._stats[key] = value

    def flush(self, stage: Optional[str] = None,

              current_file: Optional[str] = None) -> None:

        fields: Dict[str, Any] = {"stats": dict(self._stats)}

        if stage is not None:

            fields["stage"] = stage

        if current_file is not None:

            fields["current_file"] = current_file

        self.db.update_job(self.job_id, **fields)

    def status(self) -> str:

        row = self.db.get_job(self.job_id) or {}

        return row.get("status", JobStatus.PENDING)

    def is_cancelled(self) -> bool:

        row = self.db.get_job(self.job_id) or {}

        return bool(row.get("cancel_flag"))

    def is_paused(self) -> bool:

        row = self.db.get_job(self.job_id) or {}

        return bool(row.get("pause_flag"))

    def set_status(self, status: str, error: str = "") -> None:

        fields: Dict[str, Any] = {"status": status}

        if error:

            fields["error"] = error

        self.db.update_job(self.job_id, **fields)

    def mark_running(self) -> None:

        self.set_status(JobStatus.RUNNING)

    def mark_paused(self) -> None:

        self.set_status(JobStatus.PAUSED)

    def mark_stopped(self) -> None:

        self.set_status(JobStatus.STOPPED)

    def mark_completed(self) -> None:

        self.flush()

        self.set_status(JobStatus.COMPLETED)

    def mark_failed(self, error: str) -> None:

        self.flush()

        self.set_status(JobStatus.FAILED, error=error)

    def save_checkpoint(self, key: str, state: Dict[str, Any]) -> None:

        self.db.save_checkpoint(self.job_id, key, state)

        self.bump("checkpoints_saved")

    def load_checkpoint(self, key: str) -> Optional[Dict[str, Any]]:

        return self.db.load_checkpoint(self.job_id, key)

    def record_error(self, context: str, message: str, detail: str = "") -> None:

        self.db.record_error(context, message, job_id=self.job_id, detail=detail)

        self.bump("failed_requests")

class JobManager:

    def __init__(self, db: Database):

        self.db = db

    def create(self, job_type: str, params: Dict[str, Any]) -> JobHandle:

        job_id = self.db.create_job(job_type, params)

        return JobHandle(db=self.db, job_id=job_id)

    def handle(self, job_id: int) -> JobHandle:

        h = JobHandle(db=self.db, job_id=job_id)

        h.refresh()

        return h

    def list(self, active_only: bool = False) -> List[Dict[str, Any]]:

        return self.db.list_jobs(active_only=active_only)

    def pause(self, job_id: int) -> None:

        self.db.set_job_control(job_id, pause=True)

    def resume(self, job_id: int) -> None:

        self.db.set_job_control(job_id, pause=False)

        row = self.db.get_job(job_id)

        if row and row["status"] == JobStatus.PAUSED:

            self.db.update_job(job_id, status=JobStatus.RUNNING)

    def stop(self, job_id: int) -> None:

        self.db.set_job_control(job_id, cancel=True)

        self.db.update_job(job_id, status=JobStatus.STOPPING)

    def active_job(self) -> Optional[Dict[str, Any]]:

        jobs = self.db.list_jobs(active_only=True, limit=1)

        return jobs[0] if jobs else None
