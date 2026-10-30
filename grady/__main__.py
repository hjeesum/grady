"""Entry point for `python -m grady`. Fetches jobs from Adzuna and stores the new ones."""

from collections import Counter

from grady import adzuna
from grady.config import load_settings
from grady.storage import JobStore


def main() -> None:
    settings = load_settings()
    search = settings.search

    all_jobs = []
    for term in search.terms:
        jobs = adzuna.fetch_all(term, search.max_pages_per_term, search.max_days_old)
        print(f"'{term}': {len(jobs)} jobs")
        all_jobs.extend(jobs)

    store = JobStore()
    new_jobs = store.save_new(all_jobs)
    print(f"\nFetched {len(all_jobs)} jobs, {len(new_jobs)} are new.")
    print(f"Database now holds {store.count()} jobs.")
    print(f"Work mode of new jobs: {dict(Counter(job.work_mode for job in new_jobs))}")
    store.close()


if __name__ == "__main__":
    main()
