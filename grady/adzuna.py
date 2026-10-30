"""Fetch jobs from the Adzuna API (UK endpoint).

API docs: https://developer.adzuna.com/docs/search
"""

from datetime import datetime

from grady.config import get_secret
from grady.http_utils import get_with_retries
from grady.models import Job, detect_work_mode
from grady.ratelimit import RateLimiter

# "gb" is the UK endpoint. We send no location ("where") so results cover the whole UK.
SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
RESULTS_PER_PAGE = 50  # the maximum Adzuna allows per request

# Adzuna's free tier allows about 25 requests per minute. One request every
# 2.5 seconds keeps us safely under that.
_rate_limiter = RateLimiter(min_interval_seconds=2.5)


def fetch_all(term: str, max_pages: int, max_days_old: int) -> list[Job]:
    """Fetch every page of results for a search term, up to max_pages."""
    jobs = []
    for page in range(1, max_pages + 1):
        page_jobs = fetch_page(term, page, max_days_old)
        jobs.extend(page_jobs)
        # A page with fewer than a full page of results is the last one, so we
        # stop without spending a request on an empty page.
        if len(page_jobs) < RESULTS_PER_PAGE:
            break
    return jobs


def fetch_page(term: str, page: int, max_days_old: int) -> list[Job]:
    """Fetch one page of results for a search term. Pages start at 1."""
    params = {
        "app_id": get_secret("ADZUNA_APP_ID"),
        "app_key": get_secret("ADZUNA_APP_KEY"),
        "what": term,
        "results_per_page": RESULTS_PER_PAGE,
        "max_days_old": max_days_old,
        "sort_by": "date",
    }
    response = get_with_retries(
        SEARCH_URL.format(page=page), params, _rate_limiter, f"Adzuna '{term}' page {page}"
    )
    return [parse_job(result) for result in response.json()["results"]]


def parse_job(result: dict) -> Job:
    """Convert one raw Adzuna result into a Job."""
    # Adzuna estimates a salary when the advert has none ("salary_is_predicted": "1").
    # An estimate isn't what the employer offers, so we treat it as unknown.
    if result.get("salary_is_predicted") == "1":
        salary_min = salary_max = None
    else:
        salary_min = _to_int(result.get("salary_min"))
        salary_max = _to_int(result.get("salary_max"))

    title = result["title"].strip()
    location = result.get("location", {}).get("display_name", "").strip()
    # Adzuna's "description" is a short snippet of the advert, not the full text.
    description = result.get("description", "")

    return Job(
        source="adzuna",
        source_id=str(result["id"]),
        title=title,
        company=result.get("company", {}).get("display_name", "").strip(),
        location=location,
        work_mode=detect_work_mode(f"{title} {location} {description}"),
        salary_min=salary_min,
        salary_max=salary_max,
        url=result["redirect_url"],
        # Adzuna dates look like "2026-10-29T12:34:56Z"
        posted_at=datetime.fromisoformat(result["created"].replace("Z", "+00:00")),
    )


def _to_int(value) -> int | None:
    # Some adverts give a salary of 0, which means "not stated", not "unpaid".
    return int(value) if value else None
