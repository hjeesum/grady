"""Load settings from config.yaml and secrets from environment variables / .env."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class SearchSettings:
    terms: list[str]
    max_pages_per_term: int
    max_days_old: int


@dataclass(frozen=True)
class FilterSettings:
    preferred_cities: list[str]
    remote_ok: bool
    min_salary: int
    include_keywords: list[str]
    exclude_keywords: list[str]


@dataclass(frozen=True)
class EmailSettings:
    max_sponsor_jobs: int
    max_agency_jobs: int


@dataclass(frozen=True)
class Settings:
    search: SearchSettings
    filters: FilterSettings
    email: EmailSettings
    known_agencies: list[str]


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    """Read config.yaml and return it as typed Settings.

    A missing or misspelled key raises an error here, at startup, instead of
    failing halfway through a run.
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    search = raw["search"]
    filters = raw["filters"]

    if not search["terms"]:
        raise ValueError("config.yaml: search.terms must list at least one search term")

    return Settings(
        search=SearchSettings(
            terms=list(search["terms"]),
            max_pages_per_term=int(search["max_pages_per_term"]),
            max_days_old=int(search["max_days_old"]),
        ),
        filters=FilterSettings(
            preferred_cities=list(filters["preferred_cities"]),
            remote_ok=bool(filters["remote_ok"]),
            min_salary=int(filters["min_salary"]),
            # An empty list in YAML ("include_keywords:" with nothing under it) loads as None.
            include_keywords=[k.lower() for k in filters["include_keywords"] or []],
            exclude_keywords=[k.lower() for k in filters["exclude_keywords"] or []],
        ),
        email=EmailSettings(
            max_sponsor_jobs=int(raw["email"]["max_sponsor_jobs"]),
            max_agency_jobs=int(raw["email"]["max_agency_jobs"]),
        ),
        known_agencies=list(raw["agencies"]["known_names"]),
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
