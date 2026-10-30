"""Fetch jobs from the Adzuna API (UK endpoint).

API docs: https://developer.adzuna.com/docs/search
"""

from datetime import datetime

import requests

from grady.config import get_secret
from grady.models import Job

# "gb" is the UK endpoint. We send no location ("where") so results cover the whole UK.
SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
RESULTS_PER_PAGE = 50  # the maximum Adzuna allows per request
TIMEOUT_SECONDS = 30


class AdzunaError(Exception):
    pass


def fetch_page(term: str, page: int = 1) -> list[Job]:
    """Fetch one page of results for a search term. Pages start at 1."""
    params = {
        "app_id": get_secret("ADZUNA_APP_ID"),
        "app_key": get_secret("ADZUNA_APP_KEY"),
        "what": term,
        "results_per_page": RESULTS_PER_PAGE,
        "sort_by": "date",
    }
    response = requests.get(SEARCH_URL.format(page=page), params=params, timeout=TIMEOUT_SECONDS)

    # Don't use response.raise_for_status(): its error message includes the full
    # URL, which contains our API key, and that would end up in logs.
    if response.status_code != 200:
        raise AdzunaError(f"Adzuna returned HTTP {response.status_code} for '{term}' page {page}")

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

    return Job(
        source="adzuna",
        source_id=str(result["id"]),
        title=result["title"].strip(),
        company=result.get("company", {}).get("display_name", "").strip(),
        location=result.get("location", {}).get("display_name", "").strip(),
        salary_min=salary_min,
        salary_max=salary_max,
        url=result["redirect_url"],
        # Adzuna dates look like "2026-10-29T12:34:56Z"
        posted_at=datetime.fromisoformat(result["created"].replace("Z", "+00:00")),
    )


def _to_int(value) -> int | None:
    return int(value) if value is not None else None
