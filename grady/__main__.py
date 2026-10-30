"""Entry point for `python -m grady`. For now it only checks the setup."""

from grady.config import load_settings


def main() -> None:
    settings = load_settings()
    print(f"Loaded {len(settings.search.terms)} search terms: {settings.search.terms}")
    print(f"Preferred cities: {settings.filters.preferred_cities}")
    print(f"Remote OK: {settings.filters.remote_ok}")
    print(f"Minimum salary: £{settings.filters.min_salary:,}")
    print(f"Excluded title keywords: {settings.filters.exclude_keywords}")


if __name__ == "__main__":
    main()
