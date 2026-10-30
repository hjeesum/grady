"""Store jobs in a SQLite database so each run can tell which jobs are new."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from grady.config import PROJECT_ROOT
from grady.models import Job

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    location      TEXT NOT NULL,
    work_mode     TEXT NOT NULL,
    salary_min    INTEGER,
    salary_max    INTEGER,
    url           TEXT NOT NULL,
    posted_at     TEXT NOT NULL,  -- ISO 8601, UTC
    first_seen_at TEXT NOT NULL,  -- when our tool first found it
    -- The same advert must never be stored twice from the same source.
    UNIQUE (source, source_id)
);
"""


class JobStore:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def save_new(self, jobs: list[Job]) -> list[Job]:
        """Insert jobs we haven't seen before. Returns only the newly inserted ones."""
        now = datetime.now(timezone.utc).isoformat()
        new_jobs = []
        # "with self.conn" wraps the inserts in one transaction: either all of
        # them are saved, or (if something crashes) none are.
        with self.conn:
            for job in jobs:
                cursor = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs (
                        source, source_id, title, company, location, work_mode,
                        salary_min, salary_max, url, posted_at, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.source, job.source_id, job.title, job.company, job.location,
                        job.work_mode, job.salary_min, job.salary_max, job.url,
                        job.posted_at.isoformat(), now,
                    ),
                )
                # rowcount is 1 if the row was inserted, 0 if it already existed.
                if cursor.rowcount == 1:
                    new_jobs.append(job)
        return new_jobs

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
