"""Finding tech sponsors in Companies House data (scripts/find_tech_sponsors.py)."""

import pytest

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
