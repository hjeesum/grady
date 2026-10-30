"""Turn UK postcodes into place names using postcodes.io (free, open ONS data, no key).

Reed gives many locations as postcodes ("LS13AD") while Adzuna gives place names
("Holbeck, Leeds"). Without converting, de-duplication across sources can't work.
"""

import re

import requests

BULK_LOOKUP_URL = "https://api.postcodes.io/postcodes"
BATCH_SIZE = 100  # the most postcodes.io accepts in one request
TIMEOUT_SECONDS = 30

# A full UK postcode, with or without the space: "LS1 3AD", "EC3R8EE", "M25DB"
POSTCODE_PATTERN = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}$", re.IGNORECASE)


def looks_like_postcode(text: str) -> bool:
    return bool(POSTCODE_PATTERN.match(text.strip()))


def postcodes_to_places(postcodes: list[str]) -> dict[str, str]:
    """Map each postcode to a place name, e.g. "LS13AD" -> "Leeds".

    London postcodes become "Borough, London" ("NW44BG" -> "Barnet, London") so
    they still match adverts that just say "London". Postcodes that can't be
    looked up are left out of the result.
    """
    places = {}
    unique = sorted(set(postcodes))
    for start in range(0, len(unique), BATCH_SIZE):
        batch = unique[start:start + BATCH_SIZE]
        try:
            response = requests.post(
                BULK_LOOKUP_URL, json={"postcodes": batch}, timeout=TIMEOUT_SECONDS
            )
        except requests.RequestException:
            # A location lookup isn't worth crashing the run for. The jobs keep
            # their postcodes; at worst a cross-source duplicate gets through.
            continue
        if response.status_code != 200:
            continue
        for item in response.json()["result"]:
            info = item["result"]
            if info is None or not info["admin_district"]:
                continue
            # The official name of some cities is e.g. "Bristol, City of"; show "Bristol".
            place = info["admin_district"].removesuffix(", City of")
            if info["region"] == "London":
                place = f"{place}, London"
            places[item["query"]] = place
    return places
