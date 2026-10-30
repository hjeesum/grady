"""Turning raw API JSON into Jobs. Uses hand-written sample JSON: no network calls."""

from datetime import datetime, timezone

import pytest

from grady import adzuna, reed
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
