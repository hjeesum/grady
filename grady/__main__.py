"""Entry point for `python -m grady`. For now it fetches all search terms from Adzuna."""

from grady import adzuna
from grady.config import load_settings


def main() -> None:
    settings = load_settings()
    search = settings.search

    all_jobs = []
    for term in search.terms:
        jobs = adzuna.fetch_all(term, search.max_pages_per_term, search.max_days_old)
        print(f"'{term}': {len(jobs)} jobs")
        all_jobs.extend(jobs)

    # The same advert can match several search terms. Counting unique Adzuna IDs
    # shows how much overlap there is (proper de-duplication comes in step 4).
    unique_ids = {job.source_id for job in all_jobs}
    print(f"\nTotal: {len(all_jobs)} jobs, {len(unique_ids)} unique adverts")


if __name__ == "__main__":
    main()
