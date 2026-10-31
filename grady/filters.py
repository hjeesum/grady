"""Apply the config.yaml filters to decide which jobs belong in the email."""

import re

from grady.config import FilterSettings
from grady.models import Job
from grady.normalise import company_starts_with


def contains_word(text: str, phrase: str) -> bool:
    """True if phrase appears in text as whole word(s), ignoring case.

    "lead" matches "Team Lead" but not "Leading". We use (?<!\\w) and (?!\\w)
    instead of \\b so that phrases starting with punctuation, like ".net", work too.
    """
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


def rejection_reason(job: Job, filters: FilterSettings) -> str | None:
    """Why this job should be left out of the email, or None if it should be included."""
    if company_starts_with(job.company, filters.blocked_companies):
        return "blocked company"
    if any(contains_word(job.title, word) for word in filters.exclude_keywords):
        return "excluded keyword in title"
    if filters.include_keywords and not any(
        contains_word(job.title, word) for word in filters.include_keywords
    ):
        return "title outside this profile"
    # Only drop a job when it states a salary that's too low; "not given" is kept.
    if job.salary_max is not None and job.salary_max < filters.min_salary:
        return "salary below minimum"
    if job.work_mode == "remote" and not filters.remote_ok:
        return "remote"
    return None
