"""Shared test fixtures. pytest loads this file automatically.

A fixture is something a test asks for by naming it as a parameter:
`def test_x(make_job):` gets the factory below.
"""

from datetime import datetime, timezone

import pytest

from grady.models import Job


def _make_job(**overrides) -> Job:
    fields = {
        "source": "adzuna",
        "source_id": "1",
        "title": "Graduate Software Engineer",
        "company": "Example Ltd",
        "location": "Leeds",
        "work_mode": "unknown",
        "salary_min": None,
        "salary_max": None,
        "url": "https://example.com/job/1",
        "posted_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
    }
    fields.update(overrides)
    return Job(**fields)


@pytest.fixture
def make_job():
    """A factory for valid Jobs: pass only the fields a test cares about."""
    return _make_job
