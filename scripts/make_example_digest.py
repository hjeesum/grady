"""Render the email with made-up jobs, for the README screenshot.

Run from the project root:  python -m scripts.make_example_digest
Writes docs/example_digest.html. Every company and job here is fictional.
"""

from collections import Counter
from datetime import date, datetime, timezone

from grady.config import PROJECT_ROOT, load_settings
from grady.digest import Digest, Section, render_html
from grady.models import Job, StoredJob

OUTPUT_PATH = PROJECT_ROOT / "docs" / "example_digest.html"

# (title, company, register name, location, work mode, min salary, max salary, day posted)
SPONSOR_JOBS = [
    ("Graduate Software Engineer", "Northwind Analytics", "Northwind Analytics Ltd",
     "Shoreditch, London", "hybrid", 34000, 38000, 30),
    ("Junior Data Engineer", "Bluefinch Health", "Bluefinch Health Limited",
     "Manchester", "unknown", 32000, 32000, 29),
    ("Graduate Developer (Python)", "Larkspur Energy", "Larkspur Energy UK PLC",
     "Leeds", "remote", None, None, 29),
    ("Graduate Cloud Engineer 2027", "Copperleaf Systems", "Copperleaf Systems Ltd",
     "Bristol", "hybrid", 33000, 36000, 28),
]
AGENCY_JOBS = [
    ("Junior .NET Developer", "Example Tech Recruitment", None,
     "Birmingham", "unknown", 30000, 35000, 29),
]


def stored(index, row, status):
    title, company, register, location, mode, low, high, day = row
    job = Job(
        source="adzuna" if index % 2 else "reed", source_id=str(index), title=title,
        company=company, location=location, work_mode=mode, salary_min=low,
        salary_max=high, url="https://example.com",
        posted_at=datetime(2026, 10, day, tzinfo=timezone.utc),
    )
    return StoredJob(id=index, job=job, sponsor_status=status, sponsor_name=register)


def main() -> None:
    settings = load_settings()
    digest = Digest(
        profile_name="Tech",
        preferred_cities=settings.profiles["tech"].filters.preferred_cities,
        sponsor=Section([stored(i, row, "sponsor") for i, row in enumerate(SPONSOR_JOBS)], cap=30),
        agency=Section([stored(i + 100, row, "agency") for i, row in enumerate(AGENCY_JOBS)], cap=10),
        no_sponsorship=Section([], cap=10),
        filtered_out=Counter({"title outside this profile": 41, "excluded keyword in title": 12}),
    )
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(render_html(digest, date(2026, 10, 30)), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
