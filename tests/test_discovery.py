"""Finding tech sponsors in Companies House data (scripts/find_tech_sponsors.py)."""

from collections import Counter

import pytest

from scripts.discover_boards import board_names, is_same_company, name_variants
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


def test_name_variants_include_trading_names():
    assert name_variants("Roofoods Ltd t/a Deliveroo") == ["roofoods", "deliveroo"]


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
