"""Store jobs in a SQLite database so each run can tell which jobs are new."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from grady.config import PROJECT_ROOT
from grady.models import Job, StoredJob
from grady.normalise import normalise_company, normalise_title, same_location

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "jobs.db"

# Bump this whenever SCHEMA changes, and add a step to MIGRATIONS so existing
# database files are upgraded instead of having to be deleted.
SCHEMA_VERSION = 4

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
    company_norm  TEXT NOT NULL,  -- normalised, for de-duplication
    title_norm    TEXT NOT NULL,
    sponsor_status TEXT,          -- "sponsor", "agency", "not_sponsor"; NULL = not checked yet
    sponsor_name   TEXT,          -- the matching name on the sponsor register
    emailed_at     TEXT,          -- when it was sent in a digest; NULL = not yet
    -- The same advert must never be stored twice from the same source.
    UNIQUE (source, source_id)
);
-- Makes the duplicate lookup fast: it searches by these two columns.
CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs (company_norm, title_norm);
"""

# MIGRATIONS[n] upgrades a version-n database to version n + 1.
MIGRATIONS = {
    2: """
        ALTER TABLE jobs ADD COLUMN sponsor_status TEXT;
        ALTER TABLE jobs ADD COLUMN sponsor_name TEXT;
    """,
    3: "ALTER TABLE jobs ADD COLUMN emailed_at TEXT;",
}


@dataclass
class SaveResult:
    new_jobs: list[Job]
    already_seen: int  # same advert (source + ID) as a previous run
    duplicates: int  # a different advert for a job we already have


class JobStore:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self._create_schema(path)

    def _create_schema(self, path: Path) -> None:
        # SQLite keeps a "user_version" number in the file, starting at 0.
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        has_jobs_table = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
        if version == 0 and not has_jobs_table:
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return

        # Upgrade one version at a time: 2 -> 3 -> 4 ...
        while version < SCHEMA_VERSION:
            if version not in MIGRATIONS:
                raise RuntimeError(
                    f"{path} uses schema version {version}, which can't be upgraded. "
                    "Delete the file and run again to rebuild it."
                )
            self.conn.executescript(MIGRATIONS[version])
            version += 1
            self.conn.execute(f"PRAGMA user_version = {version}")

    def save_new(self, jobs: list[Job]) -> SaveResult:
        """Insert jobs we haven't seen before, skipping duplicates."""
        result = SaveResult(new_jobs=[], already_seen=0, duplicates=0)
        now = datetime.now(timezone.utc).isoformat()
        # "with self.conn" wraps the inserts in one transaction: either all of
        # them are saved, or (if something crashes) none are.
        with self.conn:
            for job in jobs:
                if self._has_advert(job):
                    result.already_seen += 1
                elif self._is_duplicate(job):
                    result.duplicates += 1
                else:
                    self._insert(job, now)
                    result.new_jobs.append(job)
        return result

    def _has_advert(self, job: Job) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM jobs WHERE source = ? AND source_id = ?",
            (job.source, job.source_id),
        ).fetchone()
        return row is not None

    def _is_duplicate(self, job: Job) -> bool:
        """True if we already have this job (same company, title and location) from any advert."""
        company_norm = normalise_company(job.company)
        # With no company name we can't tell two "Graduate Developer, London"
        # adverts apart, so we don't risk merging them.
        if not company_norm:
            return False
        rows = self.conn.execute(
            "SELECT location FROM jobs WHERE company_norm = ? AND title_norm = ?",
            (company_norm, normalise_title(job.title)),
        ).fetchall()
        return any(same_location(job.location, location) for (location,) in rows)

    def _insert(self, job: Job, now: str) -> None:
        self.conn.execute(
            """
            INSERT INTO jobs (
                source, source_id, title, company, location, work_mode,
                salary_min, salary_max, url, posted_at, first_seen_at,
                company_norm, title_norm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.source, job.source_id, job.title, job.company, job.location,
                job.work_mode, job.salary_min, job.salary_max, job.url,
                job.posted_at.isoformat(), now,
                normalise_company(job.company), normalise_title(job.title),
            ),
        )

    def companies_to_classify(self) -> list[str]:
        """Companies with at least one job whose sponsor status hasn't been checked yet."""
        rows = self.conn.execute(
            "SELECT DISTINCT company FROM jobs WHERE sponsor_status IS NULL"
        ).fetchall()
        return [company for (company,) in rows]

    def set_sponsor_status(self, statuses: dict[str, tuple[str, str | None]]) -> None:
        """Save {company: (status, register name or None)} for all unchecked jobs."""
        with self.conn:
            self.conn.executemany(
                """
                UPDATE jobs SET sponsor_status = ?, sponsor_name = ?
                WHERE company = ? AND sponsor_status IS NULL
                """,
                [(status, name, company) for company, (status, name) in statuses.items()],
            )

    def jobs_to_email(self) -> list[StoredJob]:
        """Sponsor and agency jobs that haven't been sent in a digest yet."""
        rows = self.conn.execute(
            """
            SELECT id, source, source_id, title, company, location, work_mode,
                   salary_min, salary_max, url, posted_at, sponsor_status, sponsor_name
            FROM jobs
            WHERE emailed_at IS NULL AND sponsor_status IN ('sponsor', 'agency')
            """
        ).fetchall()
        return [
            StoredJob(
                id=row[0],
                job=Job(
                    source=row[1], source_id=row[2], title=row[3], company=row[4],
                    location=row[5], work_mode=row[6], salary_min=row[7],
                    salary_max=row[8], url=row[9],
                    posted_at=datetime.fromisoformat(row[10]),
                ),
                sponsor_status=row[11],
                sponsor_name=row[12],
            )
            for row in rows
        ]

    def count_by_sponsor_status(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT sponsor_status, COUNT(*) FROM jobs GROUP BY sponsor_status"
        ).fetchall()
        return dict(rows)

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
