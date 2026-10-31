"""Fetch jobs straight from employers' own job boards.

Many companies host their careers page on a job board system (an "ATS":
Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Teamtailor).
Each offers a public, key-free way to list a company's open jobs, made for
companies to show their jobs on their own website (Teamtailor as an RSS feed). Unlike Adzuna and Reed there's no search: we download every open job a
company has, then keep the UK, entry-level ones.

Which companies to fetch is listed in config.yaml; scripts/find_boards.py finds
a company's board and checks it's a sponsor before you add it.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from grady.config import BoardCompany
from grady.filters import contains_word
from grady.http_utils import ApiError, get_with_retries
from grady.models import Job, detect_work_mode
from grady.ratelimit import RateLimiter

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{token}/postings",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{token}",
    "recruitee": "https://{token}.recruitee.com/api/offers/",
    "teamtailor": "https://{token}.teamtailor.com/jobs.rss",
}
PARAMS = {
    "greenhouse": {},
    "lever": {"mode": "json"},
    "ashby": {},
    # SmartRecruiters can filter by country itself. Big companies (Bosch: 5,000
    # jobs) would otherwise take dozens of pages. 100 per page is its maximum.
    "smartrecruiters": {"country": "gb", "limit": 100},
    "workable": {},
    "recruitee": {},
    "teamtailor": {},
}

# One rate limiter per system: each system's requests are spaced out, and the
# systems are fetched in parallel (see fetch_boards). One request per
# company, and these APIs serve public careers pages, so half a second is polite.
# Workable refuses more than about one request every 10 seconds (measured Oct 2026).
_rate_limiters = {ats: RateLimiter(min_interval_seconds=10 if ats == "workable" else 0.5)
                  for ats in URLS}

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

# Jobs older than this are ignored (see recent_only).
MAX_JOB_AGE_DAYS = 365


def fetch_boards(
    companies: list[BoardCompany], entry_level_keywords: list[str]
) -> list[tuple[BoardCompany, list[Job] | Exception]]:
    """Fetch many boards. Returns (company, its jobs) or (company, the error) for each.

    One thread per system, so a slow one (Lever can take seconds per answer)
    doesn't hold up the others. Each thread uses only its own system's rate limiter.
    """
    def fetch_system(ats: str):
        results = []
        for company in companies:
            if company.ats != ats:
                continue
            try:
                results.append((company, fetch_board(ats, company.token, company.name,
                                                     entry_level_keywords)))
            except (ApiError, requests.RequestException) as error:
                results.append((company, error))
        return results

    with ThreadPoolExecutor(max_workers=len(URLS)) as pool:
        return [result for results in pool.map(fetch_system, URLS) for result in results]


def fetch_board(ats: str, token: str, company: str, entry_level_keywords: list[str]) -> list[Job]:
    """All UK entry-level jobs on one company's board."""
    jobs = fetch_uk_jobs(ats, token, company)
    return [job for job in jobs if is_entry_level(job.title, entry_level_keywords)]


def fetch_uk_jobs(ats: str, token: str, company: str) -> list[Job]:
    """All recent UK jobs on one company's board, any level.

    `company` is the name from config.yaml, used for sponsor matching (Lever and
    Ashby don't return a company name).
    """
    url, description = URLS[ats].format(token=token), f"{ats} board '{token}'"
    if ats != "smartrecruiters":
        response = get_with_retries(url, PARAMS[ats], _rate_limiters[ats], description)
        return recent_only(parse_board(ats, token, company, read_response(ats, response)))

    # SmartRecruiters gives at most 100 jobs per answer: ask page by page.
    postings = []
    while True:
        params = {**PARAMS[ats], "offset": len(postings)}
        page = get_with_retries(url, params, _rate_limiters[ats], description).json()
        postings += page["content"]
        if not page["content"] or len(postings) >= page["totalFound"]:
            return recent_only(parse_board(ats, token, company, {"content": postings}))


def recent_only(jobs: list[Job], now: datetime | None = None) -> list[Job]:
    """Drop jobs posted more than MAX_JOB_AGE_DAYS ago.

    Some boards are abandoned: the company moved to another system but never
    closed its old jobs (Lyst's SmartRecruiters board still listed jobs from
    2016). A job that old is almost certainly closed.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=MAX_JOB_AGE_DAYS)
    return [job for job in jobs if job.posted_at >= cutoff]


def read_response(ats: str, response):
    """The board's data: parsed JSON, or for Teamtailor the RSS text."""
    return response.text if ats == "teamtailor" else response.json()


def parse_board(ats: str, token: str, company: str, data) -> list[Job]:
    """Turn one board's data into Jobs, keeping UK jobs only."""
    if ats == "greenhouse":
        postings = data["jobs"]
        parse, is_uk = _parse_greenhouse, lambda p: is_uk_location(p["location"]["name"])
    elif ats == "lever":
        postings = data  # Lever returns a plain list
        parse, is_uk = _parse_lever, _lever_is_uk
    elif ats == "ashby":
        postings = data["jobs"]
        parse, is_uk = _parse_ashby, _ashby_is_uk
    elif ats == "smartrecruiters":
        postings = data["content"]
        # We asked for UK jobs only; checking again costs nothing.
        parse, is_uk = _parse_smartrecruiters, lambda p: p["location"].get("country") == "gb"
    elif ats == "workable":
        postings = data["jobs"]
        parse, is_uk = _parse_workable, _workable_is_uk
    elif ats == "recruitee":
        postings = data["offers"]
        parse, is_uk = _parse_recruitee, _recruitee_is_uk
    else:
        postings = teamtailor_items(data)
        parse, is_uk = _parse_teamtailor, _teamtailor_is_uk
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
        # Most of these systems give no salary, or only sometimes, so we don't try.
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


def _parse_smartrecruiters(p: dict, token: str, company: str) -> Job:
    location = p["location"]
    mode = "remote" if location.get("remote") else "hybrid" if location.get("hybrid") else ""
    return _job(
        "smartrecruiters", token, p["id"], p["name"], company, location.get("city") or "",
        f"https://jobs.smartrecruiters.com/{p['company']['identifier']}/{p['id']}",
        datetime.fromisoformat(p["releasedDate"]).astimezone(timezone.utc),  # "...T17:47:00.310Z"
        extra_text=mode,
    )


def _workable_is_uk(p: dict) -> bool:
    return p.get("country") == "United Kingdom" or any(
        loc.get("countryCode") == "GB" for loc in p.get("locations", []))


def _parse_workable(p: dict, token: str, company: str) -> Job:
    return _job(
        "workable", token, p["shortcode"], p["title"], company,
        ", ".join(part for part in [p.get("city"), p.get("country")] if part),
        p["url"],
        # Only a date ("2026-05-29"): count it as midnight UTC.
        datetime.fromisoformat(p["published_on"]).replace(tzinfo=timezone.utc),
        extra_text="remote" if p.get("telecommuting") else "",
    )


def _recruitee_is_uk(p: dict) -> bool:
    return p.get("country_code") == "GB" or any(
        loc.get("country_code") == "GB" for loc in p.get("locations", []))


def _parse_recruitee(p: dict, token: str, company: str) -> Job:
    mode = "remote" if p.get("remote") else "hybrid" if p.get("hybrid") else ""
    return _job(
        "recruitee", token, p["id"], p["title"], company, p.get("location") or "",
        p["careers_url"],
        datetime.strptime(p["published_at"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc),
        extra_text=mode,
    )


# Teamtailor's own tags (the location details) are in this XML namespace.
TT = "{https://teamtailor.com/locations}"


def teamtailor_items(rss: str) -> list[dict]:
    """The jobs in a Teamtailor RSS feed, as dicts like the other systems give."""
    # ElementTree is safe here: Python's bundled XML parser (expat 2.4.1+) blocks
    # the known "XML bomb" attacks.
    channel = ElementTree.fromstring(rss).find("channel")
    return [
        {
            "title": item.findtext("title", ""),
            "link": item.findtext("link", ""),
            "guid": item.findtext("guid", ""),
            "pubDate": item.findtext("pubDate", ""),
            "remoteStatus": item.findtext("remoteStatus", ""),
            "cities": [loc.findtext(f"{TT}city", "") for loc in item.iter(f"{TT}location")],
            "countries": [loc.findtext(f"{TT}country", "") for loc in item.iter(f"{TT}location")],
        }
        for item in channel.iter("item")
    ]


def _teamtailor_is_uk(p: dict) -> bool:
    return any(is_uk_location(country) for country in p["countries"])


def _parse_teamtailor(p: dict, token: str, company: str) -> Job:
    return _job(
        "teamtailor", token, p["guid"], p["title"], company,
        ", ".join(dict.fromkeys(city for city in p["cities"] if city)),
        p["link"],
        parsedate_to_datetime(p["pubDate"]).astimezone(timezone.utc),  # "Thu, 29 Oct 2026 13:25:57 +0100"
        # remoteStatus is "hybrid", "fully" (remote) or "none"
        extra_text="remote" if p["remoteStatus"] == "fully" else p["remoteStatus"],
    )
