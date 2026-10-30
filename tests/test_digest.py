from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from grady.config import EmailSettings, FilterSettings, Profile
from grady.digest import build_digest, format_salary, render_html, render_text
from grady.filters import contains_word, rejection_reason
from grady.models import StoredJob


def make_settings(max_sponsor_jobs=2):
    """A test profile with known filters and caps (independent of config.yaml)."""
    filters = FilterSettings(
        preferred_cities=["London"],
        remote_ok=True,
        min_salary=30000,
        include_keywords=["software", "developer", ".net"],
        exclude_keywords=["senior", "lead"],
        blocked_companies=[],
    )
    return SimpleNamespace(
        filters=filters,
        profile=Profile(id="tech", name="Tech", terms=["x"], filters=filters),
        email=EmailSettings(max_sponsor_jobs=max_sponsor_jobs, max_agency_jobs=2),
    )


@pytest.fixture
def settings():
    return make_settings()


def digest_of(jobs, settings):
    return build_digest(jobs, settings.profile, settings.email)


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


def test_blocked_company_is_left_out(settings, make_job):
    filters = replace(settings.filters, blocked_companies=["itol recruit"])
    assert rejection_reason(make_job(company="ITOL Recruit"), filters) == "blocked company"
    assert rejection_reason(make_job(company="Itol Recruit Ltd"), filters) == "blocked company"


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
    settings = make_settings(max_sponsor_jobs=10)
    order = [s.id for s in digest_of(jobs, settings).sponsor.jobs]
    assert order == [3, 2, 1]


def test_sections_are_capped_with_a_count_of_the_rest(settings, stored):
    jobs = [stored(i) for i in range(5)] + [stored(10, status="agency")]
    digest = digest_of(jobs, settings)
    assert len(digest.sponsor.jobs) == 2 and digest.sponsor.more == 3
    assert len(digest.agency.jobs) == 1 and digest.agency.more == 0


def test_filtered_jobs_are_counted_by_reason(settings, stored):
    digest = digest_of([stored(1, title="Lead Developer"), stored(2)], settings)
    assert digest.filtered_out == {"excluded keyword in title": 1}


def test_reported_ids_include_overflow_but_not_filtered(settings, stored):
    # Cap is 2: jobs 1-3 are reported (2 shown + "1 more"); job 9 is filtered out,
    # so it stays unemailed and reappears if the filter is loosened.
    jobs = [stored(1), stored(2), stored(3), stored(9, title="Senior Developer")]
    assert sorted(digest_of(jobs, settings).reported_ids) == [1, 2, 3]


def test_render_text_lists_jobs_and_links(settings, stored):
    digest = digest_of([stored(1, title="Graduate Software Engineer")], settings)
    text = render_text(digest, date(2026, 10, 30))
    assert "Graduate Software Engineer" in text
    assert "https://example.com/job/1" in text


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
    digest = digest_of([stored(1, title="Software <script>alert(1)</script> & Co")], settings)
    html = render_html(digest, date(2026, 10, 30))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
