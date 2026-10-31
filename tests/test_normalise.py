import pytest

from grady.normalise import (
    company_starts_with,
    location_parts,
    normalise_company,
    normalise_title,
    same_location,
)


# parametrize runs the same test once per row, and reports each row separately.
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Thales UK Limited", "thales"),
        ("Thales UK Ltd.", "thales"),
        ("Capgemini UK PLC", "capgemini"),
        ("Accenture (UK) Limited", "accenture"),
        ("Marks & Spencer PLC", "marks and spencer"),
        ("The Hut Group", "hut"),
        ("  Asian African Foods Ltd ", "asian african foods"),
        ("F8 FERROVIAL CONSTRUCTION  LIMITED", "f8 ferrovial construction"),
        # NHS naming variants found on NHS Jobs vs the sponsor register
        ("Barts Health NHS Trust", "barts health"),
        ("Barts Health National Health Service Trust", "barts health"),
        ("Berkshire Healthcare Foundation Trust", "berkshire healthcare"),
        ("Berkshire Healthcare NHS Foundation Trust", "berkshire healthcare"),
        ("Doncaster & Bassetlaw Teaching Hospitals NHS FT", "doncaster and bassetlaw teaching hospitals"),
        ("Derbyshire Community Health Services NHSFT", "derbyshire community health services"),
        ("East Midlands Ambulance Service NHS Trust", "east midlands ambulance service"),
    ],
)
def test_normalise_company(raw, expected):
    assert normalise_company(raw) == expected


def test_normalise_company_only_strips_suffixes_from_the_end():
    # "Limited" at the start is part of the name, not a legal suffix.
    assert normalise_company("Limited Edition Games Ltd") == "limited edition games"


def test_normalise_company_keeps_a_name_that_is_only_a_suffix_word():
    # Stripping must never leave an empty name.
    assert normalise_company("Group") == "group"


def test_normalise_company_empty():
    assert normalise_company("") == ""


@pytest.mark.parametrize(
    "company, expected",
    [
        ("Hays", True),
        ("HAYS PLC", True),  # suffix stripped before comparing
        ("Hays Construction and Property", True),
        ("Haysmith Ltd", False),  # whole words only
        ("", False),
    ],
)
def test_company_starts_with(company, expected):
    assert company_starts_with(company, ["Hays"]) is expected


def test_normalise_title_ignores_punctuation_and_case():
    assert normalise_title("Software Engineer - Graduate") == normalise_title(
        "software engineer (graduate)"
    )


def test_location_parts_removes_noise_words():
    assert location_parts("Fenchurch St, Central London") == {"fenchurch st", "london"}
    assert location_parts("Hillhead, Glasgow City Centre") == {"hillhead", "glasgow"}


@pytest.mark.parametrize(
    "a, b",
    [
        ("Holbeck, Leeds", "Leeds"),
        ("Barnet, London", "Fenchurch St, Central London"),
        ("Glasgow City", "Hillhead, Glasgow City Centre"),
        ("Manchester, Greater Manchester", "Manchester"),
    ],
)
def test_same_location_matches(a, b):
    assert same_location(a, b)
    assert same_location(b, a)  # order mustn't matter


@pytest.mark.parametrize(
    "a, b",
    [
        ("Holbeck, Leeds", "Deritend, Birmingham"),
        ("Leeds", ""),
    ],
)
def test_same_location_does_not_match(a, b):
    assert not same_location(a, b)
