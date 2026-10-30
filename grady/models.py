"""The Job record that every job source (Adzuna, Reed, ...) converts its results into."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Job:
    source: str  # "adzuna" or "reed"
    source_id: str  # the job's ID inside that source
    title: str
    company: str
    location: str
    salary_min: int | None  # None when the advert gives no salary
    salary_max: int | None
    url: str
    posted_at: datetime
