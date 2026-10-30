"""Fetch jobs from the Reed API.

API docs: https://www.reed.co.uk/developers/jobseeker
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from grady.config import get_secret
from grady.http_utils import get_with_retries
from grady.models import Job, detect_work_mode
from grady.postcodes import looks_like_postcode, postcodes_to_places
from grady.ratelimit import RateLimiter

SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"
RESULTS_PER_PAGE = 100  # the maximum Reed allows per request

# Reed doesn't publish a clear limit, so we use the same polite spacing as Adzuna.
_rate_limiter = RateLimiter(min_interval_seconds=2.5)

# Some contract adverts give a daily or hourly rate (e.g. 450) instead of an
# annual salary. Anything below this can't be an annual salary.
MIN_ANNUAL_SALARY = 1000


def fetch_all(term: str, max_pages: int, max_days_old: int) -> list[Job]:
    """Fetch every page of results for a search term, up to max_pages."""
    jobs = []
    for page in range(1, max_pages + 1):
        page_jobs = fetch_page(term, page)
        jobs.extend(page_jobs)
        if len(page_jobs) < RESULTS_PER_PAGE:
            break

    # Unlike Adzuna, Reed's search has no "posted in the last N days" option,
    # so we filter by date ourselves.
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    jobs = [job for job in jobs if job.posted_at >= cutoff]

    return _replace_postcodes(jobs)


def fetch_page(term: str, page: int) -> list[Job]:
    """Fetch one page of results. Reed pages by "skip N results", so we convert."""
    params = {
        "keywords": term,
        "resultsToTake": RESULTS_PER_PAGE,
        "resultsToSkip": (page - 1) * RESULTS_PER_PAGE,
    }
    # Reed uses HTTP Basic auth: the API key is the username, the password is empty.
    # This sends the key in a header, not the URL.
    response = get_with_retries(
        SEARCH_URL, params, _rate_limiter, f"Reed '{term}' page {page}",
        auth=(get_secret("REED_API_KEY"), ""),
    )
    return [parse_job(result) for result in response.json()["results"]]


def parse_job(result: dict) -> Job:
    """Convert one raw Reed result into a Job."""
    title = result["jobTitle"].strip()
    location = (result.get("locationName") or "").strip()
    # Reed's "jobDescription" is a short snippet of the advert, not the full text.
    description = result.get("jobDescription") or ""

    return Job(
        source="reed",
        source_id=str(result["jobId"]),
        title=title,
        company=(result.get("employerName") or "").strip(),
        location=location,
        work_mode=detect_work_mode(f"{title} {location} {description}"),
        salary_min=_annual_salary(result.get("minimumSalary")),
        salary_max=_annual_salary(result.get("maximumSalary")),
        url=result["jobUrl"],
        # Reed dates look like "22/10/2026" (day first, no time)
        posted_at=datetime.strptime(result["date"], "%d/%m/%Y").replace(tzinfo=timezone.utc),
    )


def _annual_salary(value) -> int | None:
    if not value or value < MIN_ANNUAL_SALARY:
        return None
    return int(value)


def _replace_postcodes(jobs: list[Job]) -> list[Job]:
    """Swap postcode locations for place names, looking them all up in one go."""
    postcodes = [job.location for job in jobs if looks_like_postcode(job.location)]
    places = postcodes_to_places(postcodes)
    # Job is frozen (can't be changed), so replace() makes a copy with a new location.
    return [
        replace(job, location=places[job.location]) if job.location in places else job
        for job in jobs
    ]
