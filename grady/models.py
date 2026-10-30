"""The Job record that every job source (Adzuna, Reed, ...) converts its results into."""

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Job:
    source: str  # "adzuna" or "reed"
    source_id: str  # the job's ID inside that source
    title: str
    company: str
    location: str
    work_mode: str  # "remote", "hybrid" or "unknown"
    salary_min: int | None  # None when the advert gives no salary
    salary_max: int | None
    url: str
    posted_at: datetime


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
