"""Load settings from config.yaml and secrets from environment variables / .env."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
# Written by scripts/discover_boards.py; read next to config.yaml if it exists.
DISCOVERED_BOARDS_FILE = "boards_discovered.yaml"

# Sources a profile searches when config.yaml doesn't list any.
DEFAULT_SOURCES = ["adzuna", "reed"]

# Job board systems grady/boards.py can read (a test checks the two lists agree).
BOARD_SYSTEMS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "teamtailor",
                 "workday"]


@dataclass(frozen=True)
class SearchSettings:
    max_pages_per_term: int
    max_days_old: int


@dataclass(frozen=True)
class FilterSettings:
    preferred_cities: list[str]
    remote_ok: bool
    min_salary: int
    include_keywords: list[str]
    exclude_keywords: list[str]
    blocked_companies: list[str]


@dataclass(frozen=True)
class Profile:
    """One kind of job (e.g. tech, healthcare): its searches and its filters."""
    id: str  # the key in config.yaml, e.g. "tech"
    name: str  # shown in the email, e.g. "Tech"
    terms: list[str]
    sources: list[str]  # which job sources to search with this profile's terms
    filters: FilterSettings  # the shared filters merged with this profile's own


@dataclass(frozen=True)
class EmailSettings:
    max_sponsor_jobs: int
    max_agency_jobs: int


@dataclass(frozen=True)
class BoardCompany:
    name: str  # used for sponsor matching, so ideally the name on the register
    ats: str  # one of BOARD_SYSTEMS, e.g. "greenhouse"
    token: str  # the company's board name in that system, e.g. "monzo"
    discovered: bool = False  # True: from boards_discovered.yaml, not checked by hand


@dataclass(frozen=True)
class BoardSettings:
    entry_level_keywords: list[str]  # a board job's title must contain one
    companies: list[BoardCompany]
    wrong_boards: list[str]  # "ats:token" boards discovery matched to the wrong company


@dataclass(frozen=True)
class Settings:
    search: SearchSettings
    profiles: dict[str, Profile]
    my_profile: str  # which profile's digest is emailed to EMAIL_TO
    email: EmailSettings
    known_agencies: list[str]
    boards: BoardSettings
    signup_url: str | None  # the public page's "get these by email" form; None = no form

    def terms_for(self, source: str) -> list[str]:
        """The search terms to send to one source: every profile that uses it, each term once.

        "Search once, match many": we fetch these once per run, then pick each
        profile's jobs out of the database. API usage grows with the number of
        terms, not with the number of profiles or people.
        """
        # dict.fromkeys removes duplicates but keeps the original order.
        return list(dict.fromkeys(
            term for p in self.profiles.values() if source in p.sources for term in p.terms
        ))


def _lower_list(value) -> list[str]:
    # An empty list in YAML ("include_keywords:" with nothing under it) loads as None.
    return [item.lower() for item in value or []]


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    """Read config.yaml and return it as typed Settings.

    A missing or misspelled key raises an error here, at startup, instead of
    failing halfway through a run.
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    shared = raw["filters"]
    profiles = {}
    for profile_id, p in raw["profiles"].items():
        if not p["terms"]:
            raise ValueError(f"config.yaml: profile '{profile_id}' needs at least one search term")
        profiles[profile_id] = Profile(
            id=profile_id,
            name=p["name"],
            terms=list(p["terms"]),
            sources=list(p.get("sources") or DEFAULT_SOURCES),
            filters=FilterSettings(
                preferred_cities=list(shared["preferred_cities"]),
                remote_ok=bool(shared["remote_ok"]),
                min_salary=int(p["min_salary"]),
                include_keywords=_lower_list(p["include_keywords"]),
                # Words excluded for every profile, plus this profile's own.
                exclude_keywords=_lower_list(shared["exclude_keywords"])
                + _lower_list(p["exclude_keywords"]),
                blocked_companies=list(shared["blocked_companies"] or []),
            ),
        )

    my_profile = raw["my_profile"]
    if my_profile not in profiles:
        raise ValueError(f"config.yaml: my_profile '{my_profile}' isn't one of the profiles")

    return Settings(
        search=SearchSettings(
            max_pages_per_term=int(raw["search"]["max_pages_per_term"]),
            max_days_old=int(raw["search"]["max_days_old"]),
        ),
        profiles=profiles,
        my_profile=my_profile,
        email=EmailSettings(
            max_sponsor_jobs=int(raw["email"]["max_sponsor_jobs"]),
            max_agency_jobs=int(raw["email"]["max_agency_jobs"]),
        ),
        known_agencies=list(raw["agencies"]["known_names"]),
        boards=_load_boards(raw["boards"], path.parent / DISCOVERED_BOARDS_FILE),
        signup_url=(raw.get("site") or {}).get("signup_url") or None,
    )


def _load_boards(raw: dict, discovered_path: Path) -> BoardSettings:
    entries = [(c, False) for c in raw["companies"] or []]
    if discovered_path.exists():
        with open(discovered_path, encoding="utf-8") as f:
            entries += [(c, True) for c in yaml.safe_load(f)["companies"] or []]

    wrong_boards = list(raw.get("wrong_boards") or [])
    companies = {}
    for c, discovered in entries:
        if c["ats"] not in BOARD_SYSTEMS:
            raise ValueError(f"board '{c['name']}' has unknown ats '{c['ats']}'")
        if discovered and f"{c['ats']}:{c['token']}" in wrong_boards:
            continue  # works even before boards_discovered.yaml is regenerated
        # Hand-checked entries come first, so they win if a board is in both files.
        companies.setdefault((c["ats"], c["token"]), BoardCompany(
            name=c["name"], ats=c["ats"], token=c["token"], discovered=discovered))
    return BoardSettings(
        entry_level_keywords=_lower_list(raw["entry_level_keywords"]),
        companies=list(companies.values()),
        wrong_boards=wrong_boards,
    )


def get_secret(name: str) -> str:
    """Return a secret from the environment, loading .env first if it exists.

    On GitHub Actions there is no .env file; secrets arrive as real environment
    variables instead, so the same code works in both places.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing secret {name}. Locally, add it to .env (see .env.example). "
            "On GitHub, add it under Settings > Secrets and variables > Actions."
        )
    return value
