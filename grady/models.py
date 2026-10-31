"""The Job record that every job source (Adzuna, Reed, ...) converts its results into."""

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Job:
    source: str  # "adzuna", "reed", "nhs_jobs", or a board system (config.BOARD_SYSTEMS)
    source_id: str  # the job's ID inside that source
    title: str
    company: str
    location: str
    work_mode: str  # "remote", "hybrid" or "unknown"
    salary_min: int | None  # None when the advert gives no salary
    salary_max: int | None
    url: str
    posted_at: datetime


@dataclass(frozen=True)
class StoredJob:
    """A Job read back from the database, with what we've worked out about it."""
    id: int
    job: Job
    sponsor_status: str  # "sponsor", "agency" or "not_sponsor"
    sponsor_name: str | None  # the matching name on the sponsor register


def detect_work_mode(text: str) -> str:
    """Guess remote/hybrid from advert text, since the APIs don't say.

    Hybrid is checked first: adverts like "hybrid remote working" are hybrid.
    We return "unknown" rather than "onsite" when neither word appears, because
    many adverts simply don't mention it.
    """
    text = text.lower()
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if re.search(r"\bremote\b|\bwork from home\b|\bwfh\b", text):
        return "remote"
    return "unknown"
