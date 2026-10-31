"""Fetch jobs from NHS Jobs, the NHS's own vacancy service.

Uses the public search feed, which NHS Jobs documents as "intended to be used by
website developers wishing to embed results within their own pages or make use
of the data in some other way". No API key is needed. Spec: "NHS Jobs Self-Serve
Job Adverts API" on nhsbsa.nhs.uk. Support: nhsbsa.nhsjobs@nhsbsa.nhs.uk
"""

import re
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree

from grady.http_utils import get_with_retries
from grady.models import Job, detect_work_mode
from grady.ratelimit import RateLimiter

SEARCH_URL = "https://www.jobs.nhs.uk/api/v1/search_xml"
RESULTS_PER_PAGE = 100  # the maximum the feed allows

# NHS seniority is set by pay band. Band 5 is the entry level for registered
# nurses, midwives and allied health professionals. (Foundation doctor posts are
# recruited nationally, not through NHS Jobs, so they aren't found here.)
ENTRY_LEVEL_PAY_BANDS = "BAND_5"

# NHS Jobs doesn't publish a rate limit; use the same polite spacing as the others.
_rate_limiter = RateLimiter(min_interval_seconds=2.5)

# Salaries look like "£29426.00 to £38471.00", or "Negotiable".
SALARY_AMOUNT = re.compile(r"£\s?([\d,]+(?:\.\d+)?)")
MIN_ANNUAL_SALARY = 1000  # anything lower is an hourly or daily rate


def fetch_all(term: str, max_pages: int, max_days_old: int) -> list[Job]:
    """Fetch every page of entry-level results for a search term, up to max_pages."""
    published_from = (date.today() - timedelta(days=max_days_old)).isoformat()
    jobs = []
    for page in range(1, max_pages + 1):
        params = {
            "keyword": term,
            "limit": RESULTS_PER_PAGE,
            "page": page,
            "publishedFrom": published_from,
            "payBandFilter": ENTRY_LEVEL_PAY_BANDS,
            "sort": "publicationDateDesc",
        }
        response = get_with_retries(SEARCH_URL, params, _rate_limiter, f"NHS Jobs '{term}' page {page}")
        page_jobs = parse_response(response.content)
        jobs.extend(page_jobs)
        if len(page_jobs) < RESULTS_PER_PAGE:
            break
    return jobs


def parse_response(xml_bytes: bytes) -> list[Job]:
    # ElementTree is safe here: Python's bundled XML parser (expat 2.4.1+) blocks
    # the "billion laughs" style attacks, and this feed comes from the NHS.
    root = ElementTree.fromstring(xml_bytes)
    return [parse_vacancy(vacancy) for vacancy in root.iter("vacancyDetails")]


def parse_vacancy(vacancy: ElementTree.Element) -> Job:
    def text(tag: str) -> str:
        return (vacancy.findtext(tag) or "").strip()

    title = text("title")
    description = text("description")
    # The first location, e.g. "Daventry, NN11 4NH"
    location = (vacancy.findtext("locations/location") or "").strip()
    salary_min, salary_max = _parse_salary(text("salary"))

    return Job(
        source="nhs_jobs",
        source_id=text("id"),
        title=title,
        company=text("employer"),
        location=location,
        work_mode=detect_work_mode(f"{title} {location} {description}"),
        salary_min=salary_min,
        salary_max=salary_max,
        url=text("url"),
        # Dates look like "2026-10-05T12:17:03.548379387": nanoseconds are more
        # precision than Python's datetime accepts, so keep the first 19 characters.
        posted_at=datetime.fromisoformat(text("postDate")[:19]).replace(tzinfo=timezone.utc),
    )


def _parse_salary(salary: str) -> tuple[int | None, int | None]:
    amounts = [float(a.replace(",", "")) for a in SALARY_AMOUNT.findall(salary)]
    amounts = [int(a) for a in amounts if a >= MIN_ANNUAL_SALARY]
    if not amounts:
        return None, None
    return min(amounts), max(amounts)
