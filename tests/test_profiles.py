"""Checks on the real config.yaml profiles, so config edits can't silently break them."""

import pytest

from grady.config import load_settings
from grady.filters import rejection_reason


@pytest.fixture(scope="module")
def settings():
    return load_settings()


def test_each_source_gets_its_profiles_terms_once(settings):
    for source in ["adzuna", "reed", "nhs_jobs"]:
        terms = settings.terms_for(source)
        assert len(terms) == len(set(terms))
        for profile in settings.profiles.values():
            if source in profile.sources:
                assert set(profile.terms) <= set(terms)


def test_nhs_jobs_only_searches_healthcare_terms(settings):
    # NHS Jobs keyword search is loose; tech terms would flood the database.
    assert set(settings.terms_for("nhs_jobs")) == set(settings.profiles["healthcare"].terms)


def test_my_profile_exists(settings):
    assert settings.my_profile in settings.profiles


def test_shared_filters_apply_to_every_profile(settings):
    for profile in settings.profiles.values():
        assert "senior" in profile.filters.exclude_keywords
        assert "itol recruit" in profile.filters.blocked_companies


# (profile, job title, should it be included?)
@pytest.mark.parametrize(
    "profile_id, title, included",
    [
        ("tech", "Graduate Software Engineer", True),
        ("tech", "Staff Engineer", False),  # senior in tech
        ("tech", "Technical Product Owner - Fixed Income Data", False),
        ("tech", "Interim Financial Controller | Hardware Deep Tech", False),
        ("tech", "Junior Data Quality Analyst", True),
        ("healthcare", "Staff Nurse", True),  # entry level in nursing
        ("healthcare", "Newly Qualified Nurse - Band 5", True),
        ("healthcare", "Healthcare Assistant", False),
        ("healthcare", "Consultant Physician", False),
        ("healthcare", "Band 8A - Highly Specialist (Advanced) Pharmacist", False),
        ("healthcare", "Community B6 Physiotherapist", False),
        ("healthcare", "Sister/Charge Nurse", False),
        ("healthcare", "Physiotherapist - Acute Stroke", True),
        ("healthcare", "Special Care Baby Unit Nurse *Internal applications only*", False),
        ("engineering", "Graduate Civil Engineer", True),
        ("engineering", "Graduate Software Engineer", False),  # belongs to tech
        ("finance", "Graduate Accountant", True),
        ("finance", "Financial Controller", False),
        ("law", "Trainee Solicitor", True),
        ("law", "Legal Secretary", False),
        ("graduate_schemes", "Graduate Programme 2027 - Supply Chain", True),
        ("graduate_schemes", "Delivery Driver", False),
    ],
)
def test_profile_filters(settings, make_job, profile_id, title, included):
    filters = settings.profiles[profile_id].filters
    job = make_job(title=title, salary_min=None, salary_max=None)
    assert (rejection_reason(job, filters) is None) is included
