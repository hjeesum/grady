"""Finding tech sponsors in Companies House data (scripts/find_tech_sponsors.py)."""

from collections import Counter

import pytest

from grady.boards import URLS
from scripts.crawl_boards import PATTERNS, board_token, match_register
from scripts.discover_boards import board_names, board_text, is_good, is_same_company, name_variants
from tests.test_boards import RECRUITEE, SMARTRECRUITERS, TEAMTAILOR, WORKABLE
from scripts.find_tech_sponsors import is_tech


@pytest.mark.parametrize(
    "sics, tech",
    [
        (["62012 - Business and domestic software development"], True),
        (["70229 - Management consultancy", "63120 - Web portals"], True),  # any code counts
        (["58290 - Other software publishing"], True),
        (["58110 - Book publishing"], False),  # 58 alone isn't software
        (["64191 - Banks"], False),
        ([], False),
    ],
)
def test_is_tech(sics, tech):
    assert is_tech(sics) is tech


def test_board_names():
    first_words = Counter({"duffel": 1, "quantum": 2, "ab": 1})
    assert board_names("Duffel Technology Ltd", first_words) == ["duffeltechnology", "duffel-technology", "duffel"]
    assert board_names("Graphcore Limited", first_words) == ["graphcore"]
    # Two register companies start with "Quantum", so "quantum" alone isn't guessed.
    assert board_names("Quantum Metric (UK) Limited", first_words) == ["quantummetric", "quantum-metric"]
    assert board_names("Ab Cd Ltd", first_words) == ["abcd", "ab-cd"]  # "ab" is too short alone
    # A web address part is at most 63 characters; longer guesses crashed the probe.
    long_name = " ".join(["word"] * 14)  # 14 words: "wordword..." is 56, "word-word-..." is 69
    assert board_names(long_name, first_words) == ["word" * 14]


def test_name_variants_include_trading_names():
    assert name_variants("Roofoods Ltd t/a Deliveroo") == ["roofoods", "deliveroo"]
    assert name_variants("GCS Compliance Services Europe Unlimited Company Trading As Navex Global")[-1] \
        == "navex global"


@pytest.mark.parametrize(
    "token, names, text, same",
    [
        ("thought-machine", ["thought machine"], "Thought Machine is a cloud-native...", True),
        ("deliveroo", ["roofoods", "deliveroo"], "Deliveroo", True),
        # The "wise" Greenhouse board belongs to a US firm that never says "Wise".
        ("wise", ["wise payments"], "Acme Logistics Inc", False),
        ("palantir", ["palantir"], "Palantirs", False),  # whole words only
    ],
)
def test_is_same_company(token, names, text, same):
    assert is_same_company(token, names, text) is same


@pytest.mark.parametrize(
    "ats, data, name",
    [
        ("smartrecruiters", SMARTRECRUITERS, "wise"),
        ("workable", WORKABLE, "hugging face"),
        ("recruitee", RECRUITEE, "bunq"),
        ("teamtailor", TEAMTAILOR, "teamtailor"),
    ],
)
def test_board_text_finds_the_company_name(ats, data, name):
    assert name in board_text(ats, data).lower()


def test_every_board_system_can_be_found_in_common_crawl():
    assert set(PATTERNS) == set(URLS)


@pytest.mark.parametrize(
    "ats, url, token",
    [
        ("greenhouse", "https://boards.greenhouse.io/monzo/jobs/7343996", "monzo"),
        ("greenhouse", "https://boards.greenhouse.io/embed/job_board?for=Monzo", "monzo"),
        ("greenhouse", "https://job-boards.greenhouse.io/monzo", "monzo"),
        ("lever", "https://jobs.lever.co/palantir/6ed76ce8/apply", "palantir"),
        ("smartrecruiters", "https://jobs.smartrecruiters.com/Wise/744000158812629", "wise"),
        ("recruitee", "https://bunq.recruitee.com/o/graduate-data-scientist", "bunq"),
        ("teamtailor", "http://node4.teamtailor.com/jobs", "node4"),
        ("lever", "https://jobs.lever.co/", None),
    ],
)
def test_board_token(ats, url, token):
    assert board_token(ats, url) == token


def test_match_register_skips_names_that_fit_two_sponsors():
    register = {"duffel technology": "Duffel Technology Ltd", "spark": "Spark Ltd",
                "spark uk": "SPARK (UK) LIMITED t/a Spark"}
    tokens = {"lever": {"duffeltechnology", "spark", "unknown"}}
    found, ambiguous = match_register(tokens, register)
    assert found == [("Duffel Technology Ltd", "lever", "duffeltechnology")]
    assert ambiguous == 1  # "spark" could be either Spark


def test_match_register_needs_more_than_a_first_word():
    register = {"airwallex uk": "Airwallex (UK) Limited", "crusoe inns": "Crusoe Inns Limited"}
    found, _ = match_register({"ashby": {"airwallex", "crusoe"}}, register)
    # "UK" says nothing about the company, "Inns" does: Crusoe Inns is a pub
    # company, and the "crusoe" board belongs to a US cloud firm.
    assert found == [("Airwallex (UK) Limited", "ashby", "airwallex")]


def test_is_good():
    cache = {
        "lever:monzo": {"uk_jobs": 3, "entry_level": [], "same_company": True},
        "lever:wise": {"uk_jobs": 3, "entry_level": [], "same_company": False},
        "lever:empty": {"uk_jobs": 0, "entry_level": [], "same_company": True},
        "lever:none": None,
    }
    assert is_good(cache, "lever", "monzo", [])
    assert not is_good(cache, "lever", "monzo", ["lever:monzo"])  # marked wrong by hand
    assert not is_good(cache, "lever", "wise", [])  # name not in its adverts
    assert not is_good(cache, "lever", "empty", [])
    assert not is_good(cache, "lever", "none", [])
    assert not is_good(cache, "lever", "never-asked", [])
