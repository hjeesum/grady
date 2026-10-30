import csv

import pytest

from grady.matching import FUZZY_THRESHOLD, SponsorMatcher
from grady.normalise import normalise_company
from grady.sponsors import DEFAULT_CSV_PATH, load_sponsor_names

LABELS_PATH = DEFAULT_CSV_PATH.parents[2] / "tests" / "data" / "sponsor_match_labels.csv"


def make_matcher(register_names: list[str]) -> SponsorMatcher:
    """A matcher over a tiny made-up register, so tests are fast and need no download."""
    return SponsorMatcher({normalise_company(name): name for name in register_names})


def test_exact_match_after_normalising():
    match = make_matcher(["Capgemini UK PLC"]).match("Capgemini")
    assert match.register_name == "Capgemini UK PLC"
    assert match.method == "exact"


def test_unique_prefix_matches_brand_to_legal_name():
    match = make_matcher(["Tarmac Trading Limited", "Tarmack Limited"]).match("Tarmac")
    assert match.register_name == "Tarmac Trading Limited"
    assert match.method == "prefix"


def test_ambiguous_prefix_does_not_guess():
    matcher = make_matcher(["Saica Pack UK Ltd", "Saica Natur UK Ltd"])
    assert matcher.match("Saica") is None


def test_register_name_inside_advert_name_is_not_a_match():
    # The prefix rule only works one way: "Leonardo" is a sponsor,
    # "Leonardo Hotels" is a different company.
    assert make_matcher(["Leonardo UK Ltd"]).match("Leonardo Hotels") is None


def test_fuzzy_match_catches_small_typo():
    match = make_matcher(["Galliford Try Plc"]).match("Galiford Try")
    assert match.register_name == "Galliford Try Plc"
    assert match.method == "fuzzy"
    assert match.score >= FUZZY_THRESHOLD


@pytest.mark.parametrize(
    "advert, register",
    [
        ("Express Solicitors", "Expert Solicitors Ltd"),
        ("Erin Associates", "Ergon Associates Ltd"),
        ("DXC Technology", "MDX Technology Ltd"),
    ],
)
def test_lookalike_companies_do_not_match(advert, register):
    assert make_matcher([register]).match(advert) is None


def test_empty_company_never_matches():
    assert make_matcher(["Example Ltd"]).match("") is None


# This test uses the real register (11 MB), so it only runs once it has been
# downloaded (`python -m grady.sponsors`). It protects the threshold choice:
# if a change makes any labelled example wrong, this fails.
@pytest.mark.skipif(not DEFAULT_CSV_PATH.exists(), reason="sponsor register not downloaded")
def test_labelled_examples_have_no_wrong_matches():
    matcher = SponsorMatcher(load_sponsor_names())
    with open(LABELS_PATH, encoding="utf-8", newline="") as f:
        labels = list(csv.DictReader(f))

    wrong = []
    for row in labels:
        match = matcher.match(row["advert_company"])
        found = match.register_name if match else None
        expected = row["expected_register_name"] or None
        # Missing a match is acceptable (we chose precision over recall);
        # matching the WRONG company is not.
        if found is not None and found != expected:
            wrong.append((row["advert_company"], found))
    assert wrong == []
