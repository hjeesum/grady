"""Normalise company names, job titles and locations so they can be compared.

Different job sites format the same thing differently ("Thales UK Limited" vs
"Thales UK Ltd."). These functions reduce each to a simple, comparable form.
"""

import re

# Words that describe a company's legal form, not which company it is.
# Only removed from the END of a name, so "Limited Edition Games Ltd" keeps "limited".
COMPANY_SUFFIXES = {
    "ltd", "limited", "plc", "llp", "llc", "lp", "inc", "incorporated",
    "corp", "corporation", "co", "company", "holdings", "group", "uk", "gb",
}

# Words that make the same place look different: "Central London", "Greater Manchester".
LOCATION_NOISE = re.compile(r"\b(central|greater|city centre|city of)\b")


def _simplify(text: str) -> str:
    """Lowercase, turn "&" into "and", replace punctuation with spaces, collapse spaces."""
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalise_company(name: str) -> str:
    words = _simplify(name).split()
    if words and words[0] == "the":
        words = words[1:]
    # Strip suffixes repeatedly: "Thales UK Limited" -> "Thales UK" -> "Thales"
    while len(words) > 1 and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalise_title(title: str) -> str:
    return _simplify(title)


def location_parts(location: str) -> frozenset[str]:
    """Split a location into its comma-separated parts, normalised.

    "Fenchurch St, Central London" -> {"fenchurch st", "london"}
    """
    parts = set()
    for part in location.lower().split(","):
        part = " ".join(LOCATION_NOISE.sub(" ", part).split())
        if part:
            parts.add(part)
    return frozenset(parts)


def same_location(a: str, b: str) -> bool:
    """Two locations match if they share any part: "Holbeck, Leeds" and "Leeds" do."""
    return bool(location_parts(a) & location_parts(b))
