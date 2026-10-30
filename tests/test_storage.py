import sqlite3

import pytest

from grady.storage import SCHEMA_VERSION, JobStore


# tmp_path is a built-in pytest fixture: a fresh empty folder for each test,
# so tests never touch your real data/jobs.db.
@pytest.fixture
def store(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    yield store
    store.close()


def test_new_job_is_saved_once(store, make_job):
    first = store.save_new([make_job()])
    second = store.save_new([make_job()])
    assert len(first.new_jobs) == 1
    assert second.new_jobs == []
    assert second.already_seen == 1
    assert store.count() == 1


def test_same_job_from_another_source_is_a_duplicate(store, make_job):
    adzuna = make_job(source="adzuna", source_id="111", company="Thales UK Limited",
                      title="Graduate Software Engineer", location="Holbeck, Leeds")
    reed = make_job(source="reed", source_id="999", company="Thales UK Ltd.",
                    title="Graduate Software Engineer", location="Leeds")
    result = store.save_new([adzuna, reed])
    assert result.new_jobs == [adzuna]
    assert result.duplicates == 1


def test_duplicate_within_one_batch_is_caught(store, make_job):
    # The same job reposted with a new ID, arriving in the same run.
    result = store.save_new([make_job(source_id="1"), make_job(source_id="2")])
    assert len(result.new_jobs) == 1
    assert result.duplicates == 1


def test_same_title_in_different_cities_are_different_jobs(store, make_job):
    # Accenture posts one advert per office: you'd apply to a specific one.
    leeds = make_job(source_id="1", company="Accenture", location="Holbeck, Leeds")
    brum = make_job(source_id="2", company="Accenture", location="Deritend, Birmingham")
    assert len(store.save_new([leeds, brum]).new_jobs) == 2


def test_jobs_without_a_company_are_never_merged(store, make_job):
    a = make_job(source_id="1", company="")
    b = make_job(source_id="2", company="")
    assert len(store.save_new([a, b]).new_jobs) == 2


def test_sponsor_status_starts_unchecked_then_is_saved(store, make_job):
    store.save_new([make_job(company="Capgemini")])
    assert store.companies_to_classify() == ["Capgemini"]

    store.set_sponsor_status({"Capgemini": ("sponsor", "Capgemini UK PLC")})
    assert store.companies_to_classify() == []
    assert store.count_by_sponsor_status() == {"sponsor": 1}


def test_emailed_jobs_are_not_offered_again(store, make_job):
    store.save_new([make_job(company="Capgemini")])
    store.set_sponsor_status({"Capgemini": ("sponsor", "Capgemini UK PLC")})
    [stored] = store.jobs_to_email()

    store.mark_emailed([stored.id])
    assert store.jobs_to_email() == []


def test_version_2_database_is_upgraded_and_keeps_its_jobs(tmp_path):
    # Build a database exactly as version 2 of the code left it.
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
            title TEXT NOT NULL, company TEXT NOT NULL, location TEXT NOT NULL,
            work_mode TEXT NOT NULL, salary_min INTEGER, salary_max INTEGER,
            url TEXT NOT NULL, posted_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,
            company_norm TEXT NOT NULL, title_norm TEXT NOT NULL,
            UNIQUE (source, source_id)
        );
        INSERT INTO jobs VALUES (1, 'adzuna', '1', 'Dev', 'Acme', 'Leeds', 'unknown',
            NULL, NULL, 'u', '2026-10-01', '2026-10-01', 'acme', 'dev');
        PRAGMA user_version = 2;
    """)
    conn.close()

    store = JobStore(path)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.count() == 1
    assert store.companies_to_classify() == ["Acme"]
    store.close()
