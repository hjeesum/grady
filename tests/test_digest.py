from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from grady.config import load_settings
from grady.digest import build_digest, format_salary, render_html
from grady.filters import contains_word, rejection_reason
from grady.models import StoredJob


@pytest.fixture
def settings():
    """The real config.yaml, with filters and caps set to known values for these tests."""
    real = load_settings()
    return replace(
        real,
        filters=replace(
            real.filters,
            preferred_cities=["London"],
            remote_ok=True,
            min_salary=30000,
            include_keywords=["software", "developer", ".net"],
            exclude_keywords=["senior", "lead"],
        ),
        email=replace(real.email, max_sponsor_jobs=2, max_agency_jobs=2),
    )


@pytest.fixture
def stored(make_job):
    """Factory for StoredJobs: stored(id, status, **job fields)."""
    def _stored(id, status="sponsor", **job_fields):
        return StoredJob(id=id, job=make_job(source_id=str(id), **job_fields),
                         sponsor_status=status, sponsor_name="Example Ltd")
    return _stored


@pytest.mark.parametrize(
    "text, phrase, expected",
    [
        ("Team Lead", "lead", True),
        ("Leading Graduate Scheme", "lead", False),
        ("Graduate .NET Developer", ".net", True),
        ("Head of Data", "head of", True),
    ],
)
def test_contains_word(text, phrase, expected):
    assert contains_word(text, phrase) is expected


def test_rejection_reasons(settings, make_job):
    f = settings.filters
    assert rejection_reason(make_job(title="Senior Software Engineer"), f) == "excluded keyword in title"
    assert rejection_reason(make_job(title="Finance Graduate"), f) == "not a tech title"
    assert rejection_reason(make_job(salary_max=25000), f) == "salary below minimum"
    assert rejection_reason(make_job(salary_max=None), f) is None  # unknown salary is kept
    assert rejection_reason(make_job(), f) is None


def test_remote_jobs_dropped_when_remote_not_ok(settings, make_job):
    filters = replace(settings.filters, remote_ok=False)
    assert rejection_reason(make_job(work_mode="remote"), filters) == "remote"


def test_preferred_cities_first_then_remote_then_newest(settings, stored):
    old = datetime(2026, 10, 1, tzinfo=timezone.utc)
    new = datetime(2026, 10, 29, tzinfo=timezone.utc)
    jobs = [
        stored(1, location="Leeds", posted_at=new),
        stored(2, location="Leeds", work_mode="remote", posted_at=old),
        stored(3, location="Canary Wharf, London", posted_at=old),
    ]
    settings = replace(settings, email=replace(settings.email, max_sponsor_jobs=10))
    order = [s.id for s in build_digest(jobs, settings).sponsor.jobs]
    assert order == [3, 2, 1]


def test_sections_are_capped_with_a_count_of_the_rest(settings, stored):
    jobs = [stored(i) for i in range(5)] + [stored(10, status="agency")]
    digest = build_digest(jobs, settings)
    assert len(digest.sponsor.jobs) == 2 and digest.sponsor.more == 3
    assert len(digest.agency.jobs) == 1 and digest.agency.more == 0


def test_filtered_jobs_are_counted_by_reason(settings, stored):
    digest = build_digest([stored(1, title="Lead Developer"), stored(2)], settings)
    assert digest.filtered_out == {"excluded keyword in title": 1}


@pytest.mark.parametrize(
    "salary_min, salary_max, expected",
    [
        (None, None, "Salary not given"),
        (30000, 30000, "£30,000"),
        (28000, 35000, "£28,000 – £35,000"),
        (None, 40000, "£40,000"),
    ],
)
def test_format_salary(make_job, salary_min, salary_max, expected):
    assert format_salary(make_job(salary_min=salary_min, salary_max=salary_max)) == expected


def test_html_escapes_job_data(settings, stored):
    # A job title from an API must never be able to inject HTML into the email.
    digest = build_digest([stored(1, title="Software <script>alert(1)</script> & Co")], settings)
    html = render_html(digest, settings, date(2026, 10, 30))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
