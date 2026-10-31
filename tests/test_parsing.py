"""Turning raw API JSON into Jobs. Uses hand-written sample JSON: no network calls."""

from datetime import datetime, timezone

import pytest

from grady import adzuna, nhs_jobs, reed
from grady.models import detect_work_mode
from grady.postcodes import looks_like_postcode

ADZUNA_RESULT = {
    "id": "5913586329",
    "title": " Graduate Software Engineer ",
    "company": {"display_name": "Accenture"},
    "location": {"display_name": "Holbeck, Leeds"},
    "description": "Join our hybrid team in Leeds...",
    "salary_min": 36400,
    "salary_max": 36400,
    "salary_is_predicted": "0",
    "redirect_url": "https://www.adzuna.co.uk/jobs/details/5913586329",
    "created": "2026-10-29T12:34:56Z",
}

REED_RESULT = {
    "jobId": 57484827,
    "employerName": "Team Energy",
    "jobTitle": "Graduate Software Developer",
    "locationName": "MK58PJ",
    "minimumSalary": 27500.0,
    "maximumSalary": 30000.0,
    "date": "22/10/2026",
    "jobDescription": "Start your career...",
    "jobUrl": "https://www.reed.co.uk/jobs/graduate-software-developer/57484827",
}


def test_adzuna_parse_job():
    job = adzuna.parse_job(ADZUNA_RESULT)
    assert job.source == "adzuna"
    assert job.title == "Graduate Software Engineer"  # whitespace stripped
    assert job.company == "Accenture"
    assert job.salary_min == 36400
    assert job.work_mode == "hybrid"
    assert job.posted_at == datetime(2026, 10, 29, 12, 34, 56, tzinfo=timezone.utc)


def test_adzuna_predicted_salary_is_treated_as_unknown():
    job = adzuna.parse_job({**ADZUNA_RESULT, "salary_is_predicted": "1"})
    assert job.salary_min is None and job.salary_max is None


def test_adzuna_zero_salary_is_treated_as_unknown():
    job = adzuna.parse_job({**ADZUNA_RESULT, "salary_min": 0, "salary_max": 0})
    assert job.salary_min is None and job.salary_max is None


def test_adzuna_missing_company_becomes_empty_string():
    result = {key: value for key, value in ADZUNA_RESULT.items() if key != "company"}
    assert adzuna.parse_job(result).company == ""


def test_reed_parse_job():
    job = reed.parse_job(REED_RESULT)
    assert job.source == "reed"
    assert job.source_id == "57484827"
    assert job.salary_min == 27500
    # Reed dates are day first: 22 October, not an error for "month 22".
    assert job.posted_at == datetime(2026, 10, 22, tzinfo=timezone.utc)


def test_reed_daily_rate_is_not_an_annual_salary():
    job = reed.parse_job({**REED_RESULT, "minimumSalary": 450.0, "maximumSalary": 500.0})
    assert job.salary_min is None and job.salary_max is None


NHS_XML = b"""<?xml version='1.0' encoding='UTF-8'?><nhsJobs>
<vacancyDetails><id>5641570</id><title>Staff Nurse </title>
<description>Join our friendly ward team...</description>
<employer>West Suffolk NHS Foundation Trust</employer>
<salary>\xc2\xa329426.00 to \xc2\xa338471.00</salary>
<postDate>2026-10-26T12:17:03.548379387</postDate>
<url>https://beta.jobs.nhs.uk/candidate/jobadvert/E0132-26-2254</url>
<locations><location>Bury St Edmunds, IP33 2QZ</location><location>Thetford</location></locations>
</vacancyDetails>
<vacancyDetails><id>5649327</id><title>Staff Nurse</title><description></description>
<employer>Elysium Healthcare</employer><salary>Negotiable</salary>
<postDate>2026-10-08T08:51:05.459373824</postDate>
<url>https://beta.jobs.nhs.uk/candidate/jobadvert/E0132-26-2308</url>
<locations><location>Chigwell</location></locations></vacancyDetails>
</nhsJobs>"""


def test_nhs_jobs_parse_response():
    first, second = nhs_jobs.parse_response(NHS_XML)
    assert first.source == "nhs_jobs"
    assert first.source_id == "5641570"
    assert first.title == "Staff Nurse"
    assert first.company == "West Suffolk NHS Foundation Trust"
    assert first.location == "Bury St Edmunds, IP33 2QZ"  # the first location
    assert (first.salary_min, first.salary_max) == (29426, 38471)
    # Nanosecond timestamps are trimmed to whole seconds.
    assert first.posted_at == datetime(2026, 10, 26, 12, 17, 3, tzinfo=timezone.utc)
    assert (second.salary_min, second.salary_max) == (None, None)  # "Negotiable"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Graduate Developer - Hybrid", "hybrid"),
        ("Fully remote role", "remote"),
        ("Hybrid remote working", "hybrid"),
        ("Work from home 2 days", "remote"),
        ("Graduate Developer, Leeds", "unknown"),
        ("Remotely-managed hybridisation lab", "unknown"),  # word boundaries
    ],
)
def test_detect_work_mode(text, expected):
    assert detect_work_mode(text) == expected


@pytest.mark.parametrize("text", ["LS13AD", "LS1 3AD", "EC3R8EE", "M25DB", "sw1a1aa"])
def test_looks_like_postcode(text):
    assert looks_like_postcode(text)


@pytest.mark.parametrize("text", ["London", "United Kingdom", "LS1", ""])
def test_does_not_look_like_postcode(text):
    assert not looks_like_postcode(text)
