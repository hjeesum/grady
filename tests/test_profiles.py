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


def test_nhs_jobs_is_not_searched_with_tech_terms(settings):
    # NHS Jobs keyword search is loose; tech terms would flood the database.
    assert "nhs_jobs" not in settings.profiles["tech"].sources


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
        ("tech", "Graduate Firmware Engineer 2027", True),
        ("tech", "Graduate Accountant", False),
        ("tech", "Junior Developer - Internal applications only", False),
    ],
)
def test_profile_filters(settings, make_job, profile_id, title, included):
    filters = settings.profiles[profile_id].filters
    job = make_job(title=title, salary_min=None, salary_max=None)
    assert (rejection_reason(job, filters) is None) is included


def test_board_companies_are_listed_once(settings):
    boards = [(c.ats, c.token) for c in settings.boards.companies]
    assert len(boards) == len(set(boards))
    assert "graduate" in settings.boards.entry_level_keywords


def test_discovered_boards_are_added_after_hand_checked_ones(tmp_path):
    from grady.config import DEFAULT_CONFIG_PATH
    config = tmp_path / "config.yaml"
    config.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "boards_discovered.yaml").write_text(
        "companies:\n"
        "  - {name: Palantir Technologies, ats: lever, token: palantir}\n"  # also hand-checked
        "  - {name: Example Software, ats: ashby, token: example}\n"
        "  - {name: Academia Limited, ats: ashby, token: academia}\n",  # in wrong_boards
        encoding="utf-8",
    )
    companies = load_settings(config).boards.companies
    palantir = [c for c in companies if c.token == "palantir"]
    assert len(palantir) == 1 and palantir[0].name == "Palantir" and not palantir[0].discovered
    assert companies[-1].token == "example" and companies[-1].discovered
    assert "academia" not in [c.token for c in companies]
