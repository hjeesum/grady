"""Spot recruitment agencies, whose adverts hide the real employer."""

from grady.normalise import normalise_company

# A company name containing any of these words is treated as an agency.
AGENCY_WORDS = {
    "recruitment", "recruit", "recruiting", "recruiters",
    "resourcing", "staffing", "personnel", "employment",
}
AGENCY_PHRASES = ["search and selection"]


class AgencyDetector:
    def __init__(self, known_agencies: list[str]):
        # Normalise the config list the same way as company names, so
        # "Hays" in config.yaml matches "HAYS" in an advert.
        self.known = [normalise_company(name) for name in known_agencies]

    def is_agency(self, company: str) -> bool:
        name = normalise_company(company)
        if not name:
            return False
        if AGENCY_WORDS & set(name.split()):
            return True
        if any(phrase in name for phrase in AGENCY_PHRASES):
            return True
        # Whole-word prefix: "hays" matches "hays construction and property"
        # but not "haysmith".
        return any(name == known or name.startswith(known + " ") for known in self.known)
