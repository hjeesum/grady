"""Company job boards (Greenhouse, Lever, Ashby). Sample JSON is trimmed from real responses."""

from datetime import datetime, timezone

import pytest

from grady.boards import is_entry_level, is_uk_location, parse_board

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
