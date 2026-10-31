"""Fetch jobs straight from employers' own job boards: Greenhouse, Lever and Ashby.

Many tech companies host their careers page on one of these systems, and each
offers a public, documented, key-free API for exactly this ("build your own job
board"). Unlike Adzuna and Reed there's no search: we download every open job a
company has, then keep the UK, entry-level ones.

Which companies to fetch is listed in config.yaml; scripts/find_boards.py finds
a company's board and checks it's a sponsor before you add it.
"""

from datetime import datetime, timezone

from grady.filters import contains_word
from grady.http_utils import get_with_retries
from grady.models import Job, detect_work_mode
from grady.ratelimit import RateLimiter

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}
PARAMS = {
    "greenhouse": {},
    "lever": {"mode": "json"},
    "ashby": {},
}

# One request per company, and these APIs serve public careers pages, so a
# shorter gap than the search APIs is still polite.
_rate_limiter = RateLimiter(min_interval_seconds=1.0)

# Greenhouse has no country field, so UK jobs are recognised from the location
# text. ("Cambridge, MA" would slip through; rare enough to accept.)
UK_PLACES = [
    "uk", "united kingdom", "great britain", "england", "scotland", "wales", "northern ireland",
    "london", "manchester", "edinburgh", "bristol", "cambridge", "oxford", "birmingham",
    "leeds", "glasgow", "belfast", "cardiff", "newcastle", "sheffield", "liverpool",
    "nottingham", "reading", "brighton", "bath", "southampton", "milton keynes",
    "cheltenham", "guildford", "aberdeen", "dundee", "leicester", "coventry", "exeter",
]
# Places abroad that contain a UK name. ("York" isn't in the list above at all,
# because of "New York".)
NOT_UK = ["new south wales", "new england"]


def fetch_board(ats: str, token: str, company: str, entry_level_keywords: list[str]) -> list[Job]:
    """All UK entry-level jobs on one company's board."""
    jobs = fetch_uk_jobs(ats, token, company)
    return [job for job in jobs if is_entry_level(job.title, entry_level_keywords)]


def fetch_uk_jobs(ats: str, token: str, company: str) -> list[Job]:
    """All UK jobs on one company's board, any level.

    `company` is the name from config.yaml, used for sponsor matching (Lever and
    Ashby don't return a company name).
    """
    response = get_with_retries(
        URLS[ats].format(token=token), PARAMS[ats], _rate_limiter, f"{ats} board '{token}'"
    )
    return parse_board(ats, token, company, response.json())


def parse_board(ats: str, token: str, company: str, data) -> list[Job]:
    """Turn one board's JSON into Jobs, keeping UK jobs only."""
    if ats == "greenhouse":
        postings = data["jobs"]
        parse, is_uk = _parse_greenhouse, lambda p: is_uk_location(p["location"]["name"])
    elif ats == "lever":
        postings = data  # Lever returns a plain list
        parse, is_uk = _parse_lever, _lever_is_uk
    else:
        postings = data["jobs"]
        parse, is_uk = _parse_ashby, _ashby_is_uk
    return [parse(p, token, company) for p in postings if is_uk(p)]


def is_uk_location(text: str) -> bool:
    for place in NOT_UK:
        text = text.lower().replace(place, "")
    return any(contains_word(text, place) for place in UK_PLACES)


def is_entry_level(title: str, keywords: list[str]) -> bool:
    # Boards list every job, most of them experienced roles that don't say
    # "senior". Adzuna/Reed get this from the search terms; here we need the title
    # to say it ("Graduate", "Junior", ...).
    return any(contains_word(title, word) for word in keywords)


def _job(ats, token, posting_id, title, company, location, url, posted_at, extra_text="") -> Job:
    title = title.strip()
    return Job(
        source=ats,
        # IDs are only guaranteed unique within one board, so include the board.
        source_id=f"{token}:{posting_id}",
        title=title,
        company=company,
        location=location,
        work_mode=detect_work_mode(f"{title} {location} {extra_text}"),
        # None of the three gives salaries consistently, so we don't try.
        salary_min=None,
        salary_max=None,
        url=url,
        posted_at=posted_at,
    )


def _parse_greenhouse(p: dict, token: str, company: str) -> Job:
    return _job(
        "greenhouse", token, p["id"], p["title"], company, p["location"]["name"],
        p["absolute_url"],
        # e.g. "2025-10-21T08:12:57-04:00"; first_published can be missing on old boards.
        datetime.fromisoformat(p.get("first_published") or p["updated_at"]).astimezone(timezone.utc),
    )


def _lever_is_uk(p: dict) -> bool:
    categories = p.get("categories", {})
    locations = categories.get("allLocations") or [categories.get("location", "")]
    return p.get("country") == "GB" or any(is_uk_location(loc) for loc in locations)


def _parse_lever(p: dict, token: str, company: str) -> Job:
    return _job(
        "lever", token, p["id"], p["text"], company, p["categories"].get("location", ""),
        p["hostedUrl"],
        datetime.fromtimestamp(p["createdAt"] / 1000, tz=timezone.utc),  # milliseconds
        extra_text=p.get("workplaceType", ""),
    )


def _ashby_is_uk(p: dict) -> bool:
    country = ((p.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
    locations = [p.get("location", "")] + [s.get("location", "") for s in p.get("secondaryLocations", [])]
    return country == "United Kingdom" or any(is_uk_location(loc) for loc in locations)


def _parse_ashby(p: dict, token: str, company: str) -> Job:
    return _job(
        "ashby", token, p["id"], p["title"], company, p.get("location", ""),
        p["jobUrl"],
        datetime.fromisoformat(p["publishedAt"]).astimezone(timezone.utc),
        extra_text=p.get("workplaceType") or "",
    )
