"""Company job boards. Sample data is trimmed from real responses."""

from datetime import datetime, timezone

import pytest

from grady import boards
from grady.boards import (URLS, fetch_workday, is_entry_level, is_uk_location, parse_board, recent_only,
                          workday_posted_at, workday_uk_job_count)
from grady.config import BOARD_SYSTEMS, BoardCompany

GREENHOUSE = {"jobs": [
    {"id": 7343996, "title": "Graduate Software Engineer ", "location": {"name": "London; Remote (UK)"},
     "absolute_url": "https://job-boards.greenhouse.io/monzo/jobs/7343996",
     "first_published": "2026-10-21T08:12:57-04:00", "updated_at": "2026-10-25T05:17:09-04:00"},
    {"id": 1, "title": "Android Engineer", "location": {"name": "Barcelona"},
     "absolute_url": "https://example.com/1", "first_published": None,
     "updated_at": "2026-10-25T05:17:09-04:00"},
]}

LEVER = [
    {"id": "6ed76ce8", "text": "Software Engineer, New Grad", "country": "GB",
     "categories": {"location": "London, United Kingdom", "allLocations": ["London, United Kingdom"]},
     "workplaceType": "onsite", "createdAt": 1786469891368,
     "hostedUrl": "https://jobs.lever.co/palantir/6ed76ce8"},
    {"id": "x", "text": "Software Engineer, New Grad", "country": "US",
     "categories": {"location": "New York, NY", "allLocations": ["New York, NY"]},
     "createdAt": 1786469891368, "hostedUrl": "https://example.com/x"},
]

ASHBY = {"jobs": [
    {"id": "a571", "title": "Junior Data Engineer", "location": "Remote", "secondaryLocations": [],
     "workplaceType": "Remote", "address": {"postalAddress": {"addressCountry": "United Kingdom"}},
     "publishedAt": "2026-10-15T05:18:56.169+00:00",
     "jobUrl": "https://jobs.ashbyhq.com/lendable/a571"},
    {"id": "b", "title": "Account Manager - India", "location": "India", "secondaryLocations": [],
     "address": {"postalAddress": {"addressCountry": "India"}},
     "publishedAt": "2026-10-15T05:18:56.169+00:00", "jobUrl": "https://example.com/b"},
]}


SMARTRECRUITERS = {"content": [
    {"id": "744000158812629", "name": "Design & Research Operations Graduate",
     "company": {"identifier": "Wise", "name": "Wise"},
     "releasedDate": "2026-10-30T17:47:00.310Z",
     "location": {"city": "London", "country": "gb", "remote": False, "hybrid": True}},
]}

WORKABLE = {"name": "Hugging Face", "jobs": [
    {"title": "Junior ML Engineer", "shortcode": "81B46579FE", "telecommuting": True,
     "url": "https://apply.workable.com/j/81B46579FE", "published_on": "2026-05-29",
     "country": "United Kingdom", "city": "London",
     "locations": [{"country": "United Kingdom", "countryCode": "GB", "city": "London"}]},
    {"title": "Junior ML Engineer", "shortcode": "X", "telecommuting": True,
     "url": "https://example.com/X", "published_on": "2026-05-29", "country": "France",
     "city": "Paris", "locations": [{"country": "France", "countryCode": "FR", "city": "Paris"}]},
]}

RECRUITEE = {"offers": [
    {"id": 2800490, "title": "Graduate Data Scientist", "company_name": "bunq",
     "location": "London, United Kingdom",
     "country_code": "GB", "locations": [{"country_code": "GB"}], "remote": False, "hybrid": True,
     "careers_url": "https://careers.bunq.com/o/graduate-data-scientist",
     "published_at": "2026-10-28 13:21:58 UTC"},
    {"id": 1, "title": "Data Scientist", "location": "Amsterdam, Netherlands",
     "country_code": "NL", "locations": [{"country_code": "NL"}],
     "careers_url": "https://example.com/1", "published_at": "2026-10-28 13:21:58 UTC"},
]}

TEAMTAILOR = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel>
    <title>Teamtailor</title>
    <item>
      <title>Junior Solution Architect</title>
      <pubDate>Thu, 29 Oct 2026 13:25:57 +0100</pubDate>
      <link>https://career.teamtailor.com/jobs/8636263-junior-solution-architect</link>
      <remoteStatus>fully</remoteStatus>
      <guid>5c189e36</guid>
      <tt:locations>
        <tt:location><tt:city>Stockholm</tt:city><tt:country>Sweden</tt:country></tt:location>
        <tt:location><tt:city>London</tt:city><tt:country>United Kingdom</tt:country></tt:location>
      </tt:locations>
    </item>
    <item>
      <title>Account Executive</title>
      <pubDate>Thu, 29 Oct 2026 13:25:57 +0100</pubDate>
      <link>https://example.com/2</link>
      <remoteStatus>none</remoteStatus>
      <guid>2</guid>
      <tt:locations>
        <tt:location><tt:city>Stockholm</tt:city><tt:country>Sweden</tt:country></tt:location>
      </tt:locations>
    </item>
  </channel>
</rss>"""


def test_every_system_in_config_can_be_fetched():
    assert set(URLS) == set(BOARD_SYSTEMS)


def test_greenhouse_keeps_uk_jobs_only():
    [job] = parse_board("greenhouse", "monzo", "Monzo", GREENHOUSE)
    assert job.source == "greenhouse"
    assert job.source_id == "monzo:7343996"  # the board name keeps IDs unique
    assert job.title == "Graduate Software Engineer"
    assert job.company == "Monzo"  # from config.yaml, for sponsor matching
    assert job.work_mode == "remote"
    assert job.posted_at == datetime(2026, 10, 21, 12, 12, 57, tzinfo=timezone.utc)


def test_lever_uses_the_country_code():
    [job] = parse_board("lever", "palantir", "Palantir", LEVER)
    assert job.location == "London, United Kingdom"
    assert job.url == "https://jobs.lever.co/palantir/6ed76ce8"
    assert job.posted_at.year == 2026  # createdAt is in milliseconds


def test_ashby_uses_the_address_country():
    # "Remote" alone says nothing about the country; the address does.
    [job] = parse_board("ashby", "lendable", "Lendable", ASHBY)
    assert job.title == "Junior Data Engineer"
    assert job.work_mode == "remote"


def test_smartrecruiters_builds_the_job_link():
    [job] = parse_board("smartrecruiters", "wise", "Wise Payments", SMARTRECRUITERS)
    assert job.url == "https://jobs.smartrecruiters.com/Wise/744000158812629"
    assert job.work_mode == "hybrid"
    assert job.posted_at == datetime(2026, 10, 30, 17, 47, 0, 310000, tzinfo=timezone.utc)


def test_workable_uses_the_country_code():
    [job] = parse_board("workable", "huggingface", "Hugging Face", WORKABLE)
    assert job.location == "London, United Kingdom"
    assert job.work_mode == "remote"  # "telecommuting"
    assert job.posted_at == datetime(2026, 5, 29, tzinfo=timezone.utc)  # a date only


def test_recruitee_uses_the_country_code():
    [job] = parse_board("recruitee", "bunq", "bunq", RECRUITEE)
    assert job.source_id == "bunq:2800490"
    assert job.work_mode == "hybrid"
    assert job.posted_at == datetime(2026, 10, 28, 13, 21, 58, tzinfo=timezone.utc)


def test_teamtailor_reads_the_rss_feed():
    # A job in Stockholm AND London counts as a UK job.
    [job] = parse_board("teamtailor", "career", "Teamtailor", TEAMTAILOR)
    assert job.title == "Junior Solution Architect"
    assert job.location == "Stockholm, London"
    assert job.work_mode == "remote"  # remoteStatus "fully"
    assert job.posted_at == datetime(2026, 10, 29, 12, 25, 57, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "location, uk",
    [
        ("London", True),
        ("Cardiff, London or Remote (UK)", True),
        ("Remote - United Kingdom", True),
        ("Barcelona", False),
        ("New York, NY", False),
        ("Sydney, New South Wales", False),  # contains "Wales"
        ("Remote", False),
        # US and Canadian towns named after UK ones (seen on Target's Workday site)
        ("125 Buckland Hills Dr, Manchester,CT 06042-8701", False),
        ("Cambridge, MA", False),
        ("London, ON", False),
        ("London, United Kingdom; Boston, MA", True),
        ("Manchester, M1 4BT", True),  # a UK postcode isn't a state
        ("US - Massachusetts - Cambridge", False),
        ("3EE MANCHESTER TN (TAX JURISDICTION - COFEE), Knoxville, TN, US", False),
        ("USA - AL - Birmingham", False),
        ("United Kingdom, Edinburgh, SC, United States - Remote", True),  # names both
    ],
)
def test_is_uk_location(location, uk):
    assert is_uk_location(location) is uk


@pytest.mark.parametrize(
    "title, entry",
    [
        ("Graduate Machine Learning Engineer 2027", True),
        ("Software Engineer, New Grad", True),
        ("Junior Data Engineer", True),
        ("Backend Engineer", False),  # boards list every level; this one isn't marked junior
        ("Gradle Build Engineer", False),  # "grad" must be a whole word
    ],
)
def test_is_entry_level(title, entry):
    keywords = ["graduate", "grad", "junior", "new grad"]
    assert is_entry_level(title, keywords) is entry


def test_recent_only_drops_jobs_from_abandoned_boards(make_job):
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    fresh = make_job(title="Junior Developer", posted_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    # Lyst's old SmartRecruiters board still listed jobs from 2016.
    stale = make_job(title="Display Specialist", posted_at=datetime(2016, 12, 14, tzinfo=timezone.utc))
    assert recent_only([fresh, stale], now) == [fresh]


# Workday answers, trimmed from Barclays' careers site (Nov 2026).
WORKDAY_FACETS = {"facets": [
    {"facetParameter": "workerSubType", "values": [{"descriptor": "Graduate", "id": "a", "count": 17}]},
    {"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locations", "values": [
            {"descriptor": "Glasgow Campus", "id": "b", "count": 30},
            {"descriptor": "New York, 745 7th Avenue", "id": "c", "count": 50},
            {"descriptor": "Northampton, Barclays Campus", "id": "d", "count": 7},
        ]},
    ]},
]}
GLASGOW = {"title": "2027 Data and Analytics Graduate Programme Glasgow", "locationsText": "Glasgow Campus",
           "externalPath": "/job/Glasgow-Campus/Data-Graduate-Programme_JR-1", "postedOn": "Posted 2 Days Ago"}
TWO_PLACES = {"title": "Graduate Software Engineer", "locationsText": "2 Locations",
              "externalPath": "/job/Pune/Graduate-Software-Engineer_JR-2", "postedOn": "Posted Today"}
NEW_YORK = {"title": "Junior Analyst", "locationsText": "New York, 745 7th Avenue",
            "externalPath": "/job/New-York/Junior-Analyst_JR-3", "postedOn": "Posted 30+ Days Ago"}
EXPERIENCED = {"title": "Data Engineer", "locationsText": "Glasgow Campus",
               "externalPath": "/job/Glasgow-Campus/Data-Engineer_JR-4", "postedOn": "Posted Today"}
DETAILS = {
    # The first location is in India, but the job is in London too.
    TWO_PLACES["externalPath"]: {"location": "Pune", "additionalLocations": ["London, 1 Churchill Place"],
                                 "country": {"descriptor": "India"}},
    NEW_YORK["externalPath"]: {"location": "New York, 745 7th Avenue",
                               "country": {"descriptor": "United States of America"}},
}


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_one_broken_board_does_not_stop_the_others(monkeypatch):
    def fake_fetch_board(ats, token, company, keywords):
        if token == "broken":
            raise KeyError("externalPath")  # an answer in a shape we don't expect
        return ["a job"]

    monkeypatch.setattr(boards, "fetch_board", fake_fetch_board)
    companies = [BoardCompany(name=t, ats="workday", token=t) for t in ("broken", "fine")]
    results = dict((c.token, r) for c, r in boards.fetch_boards(companies, []))
    assert isinstance(results["broken"], KeyError)
    assert results["fine"] == ["a job"]


def test_fetch_workday(monkeypatch):
    searches, details = [], []

    def fake_request(url, params, limiter, description, json_body=None):
        if json_body:  # a search
            searches.append(json_body["searchText"])
            # Every search finds Glasgow; the job is kept once. Workday puts the
            # total only on the first page.
            # A job with no link (seen live) is skipped instead of crashing the fetch.
            no_link = {"title": "Graduate Analyst", "locationsText": "London"}
            found = ([GLASGOW, TWO_PLACES, NEW_YORK, EXPERIENCED, no_link]
                     if json_body["searchText"] == "grad" else [GLASGOW])
            return FakeResponse({"total": len(found), "jobPostings": found})
        path = url.split("/external_site")[1]
        details.append(path)
        return FakeResponse({"jobPostingInfo": DETAILS[path]})

    monkeypatch.setattr(boards, "get_with_retries", fake_request)
    jobs = fetch_workday("barclays.wd3/external_site", "Barclays", ["graduate", "junior"])

    assert searches == boards.WORKDAY_SEARCHES
    assert [job.title for job in jobs] == [GLASGOW["title"], TWO_PLACES["title"]]
    # Only entry-level jobs whose list entry shows no UK place are looked up.
    assert details == [TWO_PLACES["externalPath"], NEW_YORK["externalPath"]]
    assert jobs[1].location == "Pune, London, 1 Churchill Place"
    assert jobs[0].url == ("https://barclays.wd3.myworkdayjobs.com/external_site"
                           "/job/Glasgow-Campus/Data-Graduate-Programme_JR-1")
    assert jobs[0].source_id == "barclays.wd3/external_site:Data-Graduate-Programme_JR-1"


@pytest.mark.parametrize(
    "posted_on, days_ago",
    [("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 3 Days Ago", 3), ("Posted 30+ Days Ago", 30)],
)
def test_workday_posted_at(posted_on, days_ago):
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    assert (now - workday_posted_at(posted_on, now)).days == days_ago


def test_workday_uk_job_count_reads_nested_location_filters():
    assert workday_uk_job_count(WORKDAY_FACETS) == 30  # Glasgow; Northampton isn't in UK_PLACES
