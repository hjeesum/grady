import pytest

from grady.agencies import AgencyDetector
from grady.classify import classify_company
from grady.matching import SponsorMatcher
from grady.normalise import normalise_company


@pytest.fixture
def agencies():
    return AgencyDetector(["Hays", "Office Angels"])


@pytest.fixture
def matcher():
    register = ["HAYS PLC", "Capgemini UK PLC"]
    return SponsorMatcher({normalise_company(name): name for name in register})


@pytest.mark.parametrize(
    "company",
    [
        "Penguin Recruitment Ltd",  # keyword
        "ARCHER RESOURCING LTD",  # keyword
        "Wintermann Search & Selection Limited",  # phrase, after "&" -> "and"
        "Office Angels",  # config list
        "Hays Construction and Property",  # config list, as a whole-word prefix
    ],
)
def test_agencies_are_detected(agencies, company):
    assert agencies.is_agency(company)


@pytest.mark.parametrize("company", ["Capgemini", "Haysmith Ltd", ""])
def test_non_agencies_are_not_detected(agencies, company):
    assert not agencies.is_agency(company)


def test_agency_that_is_itself_a_sponsor_is_still_an_agency(agencies, matcher):
    # Hays sponsoring its own staff says nothing about its client.
    assert classify_company("HAYS", agencies, matcher) == ("agency", None)


def test_sponsor(agencies, matcher):
    assert classify_company("Capgemini", agencies, matcher) == ("sponsor", "Capgemini UK PLC")


def test_not_sponsor(agencies, matcher):
    assert classify_company("Express Solicitors", agencies, matcher) == ("not_sponsor", None)
