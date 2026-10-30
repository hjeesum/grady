"""Decide each company's sponsor status: "sponsor", "agency" or "not_sponsor"."""

from grady.agencies import AgencyDetector
from grady.matching import SponsorMatcher


def classify_company(
    company: str, agencies: AgencyDetector, matcher: SponsorMatcher
) -> tuple[str, str | None]:
    """Return (status, register name or None).

    The agency check comes first: some agencies (e.g. Hays) are licensed sponsors
    themselves, but that says nothing about whether their client can sponsor you.
    """
    if agencies.is_agency(company):
        return "agency", None
    match = matcher.match(company)
    if match is None:
        return "not_sponsor", None
    return "sponsor", match.register_name
