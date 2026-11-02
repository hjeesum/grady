"""The public job page (grady/site.py)."""

from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import pytest

from grady.models import StoredJob
from grady.site import build_site, public_jobs
from grady.storage import JobStore
from tests.test_digest import make_settings

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)


@pytest.fixture
def profile():
    return make_settings().profile


@pytest.fixture
def stored(make_job):
    def _stored(id, **job_fields):
        return StoredJob(id=id, job=make_job(source_id=str(id), **job_fields),
                         sponsor_status="sponsor", sponsor_name="Example Ltd")
    return _stored


def test_only_sources_that_allow_public_display(profile, stored):
    jobs = [stored(1, source="adzuna"), stored(2, source="workday"), stored(3, source="greenhouse"),
            # Reed allows only private use; NHS Jobs' terms haven't been checked.
            stored(4, source="reed"), stored(5, source="nhs_jobs")]
    assert [s.id for s in public_jobs(jobs, profile)] == [1, 2, 3]


def test_profile_filters_apply_and_newest_is_first(profile, stored):
    day = timedelta(days=1)
    jobs = [stored(1, posted_at=NOW - 2 * day), stored(2, posted_at=NOW),
            stored(3, title="Senior Software Engineer")]  # "senior" is excluded
    assert [s.id for s in public_jobs(jobs, profile)] == [2, 1]


def test_adzuna_jobs_carry_the_adzuna_label(profile, stored, tmp_path):
    build_site([stored(1, source="adzuna"), stored(2, source="workday", title="Graduate Developer")],
               profile, NOW, tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    # Adzuna's terms: every Adzuna advert is labelled "Adzuna" and links to Adzuna.
    assert html.count('href="https://www.adzuna.co.uk"') == 1


def test_job_text_is_escaped_in_page_and_feed(profile, stored, tmp_path):
    build_site([stored(1, title="Software <script>alert(1)</script> & Co")], profile, NOW, tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script>alert" not in html
    # The feed must stay valid XML even with "<" and "&" in a title.
    feed = ElementTree.parse(tmp_path / "feed.xml")
    assert feed.find("channel/item/title").text == "Software <script>alert(1)</script> & Co at Example Ltd"


def test_sponsor_jobs_since_includes_emailed_jobs_but_not_others(tmp_path, make_job):
    store = JobStore(tmp_path / "jobs.db")
    store.save_new([make_job(source_id="1", company="Sponsor Ltd"),
                    make_job(source_id="2", company="Other Ltd", title="Graduate Developer")])
    store.set_sponsor_status({"Sponsor Ltd": ("sponsor", "Sponsor Ltd"), "Other Ltd": ("not_sponsor", None)})
    store.mark_emailed([s.id for s in store.jobs_to_email()])  # emailed jobs stay on the page
    found = store.sponsor_jobs_since(datetime.now(timezone.utc) - timedelta(days=1))
    assert [s.job.company for s in found] == ["Sponsor Ltd"]
    assert store.sponsor_jobs_since(datetime.now(timezone.utc) + timedelta(days=1)) == []
    store.close()


def test_signup_box_only_when_a_form_is_set(profile, stored, tmp_path):
    build_site([stored(1)], profile, NOW, tmp_path)
    assert "Get them by email" not in (tmp_path / "index.html").read_text(encoding="utf-8")
    build_site([stored(1)], profile, NOW, tmp_path, signup_url="https://forms.gle/abc")
    assert 'href="https://forms.gle/abc"' in (tmp_path / "index.html").read_text(encoding="utf-8")
