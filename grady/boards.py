"""Fetch jobs straight from employers' own job boards.

Many companies host their careers page on a job board system (an "ATS":
Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Teamtailor).
Each offers a public, key-free way to list a company's open jobs, made for
companies to show their jobs on their own website (Teamtailor as an RSS feed). Unlike Adzuna and Reed there's no search: we download every open job a
company has, then keep the UK, entry-level ones.

Workday is different: it's the careers site of big employers (Barclays,
AstraZeneca), with no published API. We read the same data its own web page
loads, politely: a few searches per company per day, as robots.txt allows.

Which companies to fetch is listed in config.yaml; scripts/find_boards.py finds
a company's board and checks it's a sponsor before you add it.
"""

import re
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
    # The token is "host/site" from the careers site's address: Barclays'
    # barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays is
    # "barclays.wd3/external_career_site_barclays" (Workday ignores the case).
    "workday": "https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}",
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
    "workday": {},
}

# Workday can't cheaply list every job (AstraZeneca has 1,200, 20 per answer),
# but its search works, so we search for entry-level words. "grad" also finds
# "graduate" and "graduates" (it matches the start of words), but with several
# words a job needs ALL of them, so each gets its own search. Measured on
# Barclays, Nov 2026. Titles are still checked with entry_level_keywords after.
WORKDAY_SEARCHES = ["grad", "junior", "entry level", "early career", "trainee", "apprentice"]
WORKDAY_PAGE_SIZE = 20  # Workday's maximum
WORKDAY_MAX_PAGES = 5  # per search: 100 results ("grad" at Barclays: 99)
# ~6-20 requests per site made Workday take 54 minutes in one thread (Nov 2026).
# Each site is a different employer's server, so 8 sites are read at once; each
# site still gets at most one request per WORKDAY_INTERVAL_SECONDS.
WORKDAY_THREADS = 8
WORKDAY_INTERVAL_SECONDS = 0.5

# One rate limiter per system: each system's requests are spaced out, and the
# systems are fetched in parallel (see fetch_boards). One request per
# company, and these APIs serve public careers pages, so half a second is polite.
# Workable refuses more than about one request every 10 seconds (measured Oct 2026).
_rate_limiters = {ats: RateLimiter(min_interval_seconds=10 if ats == "workable" else 0.5)
                  for ats in URLS}

# Greenhouse has no country field, so UK jobs are recognised from the location
# text. US towns with UK names are handled below.
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
# "Manchester, CT", "Cambridge,MA 02139", "London, ON": US and Canadian towns named
# after UK ones (Target's Workday site looked like 159 UK jobs). Removed before
# checking, so "London, UK; Boston, MA" still counts. Capitals only: "ma" or "in"
# inside ordinary text isn't a state.
NORTH_AMERICAN_TOWN = re.compile(
    r"[\w .'-]+,\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|"
    r"MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|"
    r"ON|BC|AB|QC|NS|NB|MB|SK|NL|PE)\b")
# Other ways of writing a US place: "US - Massachusetts - Cambridge" (Amgen),
# "MANCHESTER TN ..., Binghamton, NY, US" (CACI). If a location names the US, it
# needs to name the UK too ("United Kingdom", "UK", "GBR", ...) to count.
US_NAMED = re.compile(r"\b(?:US|USA|United States)\b")
UK_NAMED = ["uk", "united kingdom", "great britain", "britain", "england", "scotland", "wales",
            "northern ireland", "gb", "gbr"]

# Jobs older than this are ignored (see recent_only).
MAX_JOB_AGE_DAYS = 365


def fetch_boards(
    companies: list[BoardCompany], entry_level_keywords: list[str]
) -> list[tuple[BoardCompany, list[Job] | Exception]]:
    """Fetch many boards. Returns (company, its jobs) or (company, the error) for each.

    One thread per system, so a slow one (Lever can take seconds per answer)
    doesn't hold up the others. Each thread uses only its own system's rate limiter.
    Workday gets several threads: see WORKDAY_THREADS.
    """
    work = []  # (system, its companies) for each thread
    for ats in URLS:
        mine = [c for c in companies if c.ats == ats]
        threads = WORKDAY_THREADS if ats == "workday" else 1
        work += [(ats, mine[i::threads]) for i in range(threads)]

    def fetch_system(ats_and_companies):
        ats, companies_here = ats_and_companies
        results = []
        for company in companies_here:
            try:
                results.append((company, fetch_board(ats, company.token, company.name,
                                                     entry_level_keywords)))
            # A board answering in an unexpected shape (KeyError etc.) is one
            # board's error, not a reason to stop every other board.
            except (ApiError, requests.RequestException, KeyError, ValueError, TypeError) as error:
                results.append((company, error))
        return results

    with ThreadPoolExecutor(max_workers=len(work)) as pool:
        return [result for results in pool.map(fetch_system, work) for result in results]


def fetch_board(ats: str, token: str, company: str, entry_level_keywords: list[str]) -> list[Job]:
    """All UK entry-level jobs on one company's board."""
    if ats == "workday":
        return fetch_workday(token, company, entry_level_keywords)
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


def workday_url(token: str) -> str:
    host, site = token.split("/")
    return URLS["workday"].format(host=host, tenant=host.split(".")[0], site=site)


def fetch_workday(token: str, company: str, entry_level_keywords: list[str]) -> list[Job]:
    """UK entry-level jobs on one Workday careers site."""
    # Its own limiter: this site's requests are spaced out, other sites run alongside.
    limiter = RateLimiter(min_interval_seconds=WORKDAY_INTERVAL_SECONDS)
    base, description = workday_url(token), f"workday site '{token}'"
    postings = {}  # by address: the same job turns up in several searches
    for search in WORKDAY_SEARCHES:
        for page in range(WORKDAY_MAX_PAGES):
            body = {"limit": WORKDAY_PAGE_SIZE, "offset": page * WORKDAY_PAGE_SIZE,
                    "searchText": search, "appliedFacets": {}}
            data = get_with_retries(base + "/jobs", {}, limiter, description, json_body=body).json()
            if page == 0:
                total = data["total"]  # only the first page has it; later ones say 0
            for posting in data["jobPostings"]:
                # Some sites list jobs with no link or no title (seen live); skip those.
                if "externalPath" in posting and "title" in posting:
                    postings.setdefault(posting["externalPath"], posting)
            if (page + 1) * WORKDAY_PAGE_SIZE >= total:
                break

    jobs = []
    for posting in postings.values():
        if not is_entry_level(posting["title"], entry_level_keywords):
            continue
        location = posting.get("locationsText", "")
        if not is_uk_location(location):
            # Often just "2 Locations", or a UK town we don't list: the job's own
            # page has its country.
            info = get_with_retries(base + posting["externalPath"], {}, limiter, description).json()
            location = _workday_uk_location(info["jobPostingInfo"])
            if not location:
                continue
        jobs.append(_parse_workday(posting, token, company, location))
    return jobs


def _workday_uk_location(info: dict) -> str:
    """The job's locations if one is in the UK, else ""."""
    locations = [info.get("location", "")] + info.get("additionalLocations", [])
    country = (info.get("country") or {}).get("descriptor", "")
    if country == "United Kingdom" or any(is_uk_location(loc) for loc in locations):
        return ", ".join(loc for loc in locations if loc)
    return ""


def workday_posted_at(posted_on: str, now: datetime | None = None) -> datetime:
    """Workday only says "Posted Today", "Posted Yesterday", "Posted 3 Days Ago" or
    "Posted 30+ Days Ago" (counted as 30: the date is only that precise)."""
    now = now or datetime.now(timezone.utc)
    text = posted_on.lower()
    if "yesterday" in text:
        days = 1
    else:
        number = re.search(r"\d+", text)
        days = int(number.group()) if number else 0  # "Posted Today"
    return now - timedelta(days=days)


def workday_uk_job_count(data: dict) -> int:
    """How many jobs a Workday site has in the UK, from the location filters in a /jobs answer.

    Used by discovery: one request instead of reading every job. The filters can
    be nested (Barclays: locationMainGroup -> locations).
    """
    def values(facets, is_location=False):
        for facet in facets:
            inner = is_location or any(w in (facet.get("facetParameter") or "").lower()
                                       for w in ("location", "country"))
            if "values" in facet:
                yield from values(facet["values"], inner)
            elif inner:
                yield facet
    return sum(v.get("count") or 0 for v in values(data.get("facets", []))
               if is_uk_location(v.get("descriptor") or ""))


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
    names_us = bool(US_NAMED.search(text))
    text = NORTH_AMERICAN_TOWN.sub("", text)
    for place in NOT_UK:
        text = text.lower().replace(place, "")
    if names_us and not any(contains_word(text, place) for place in UK_NAMED):
        return False
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


def _parse_workday(p: dict, token: str, company: str, location: str) -> Job:
    host, site = token.split("/")
    path = p["externalPath"]  # "/job/Glasgow-Campus/...-Programme-Glasgow_JR-0000129278"
    return _job(
        "workday", token, path.rsplit("/", 1)[-1], p["title"], company, location,
        f"https://{host}.myworkdayjobs.com/{site}{path}",
        workday_posted_at(p.get("postedOn", "")),
    )
