"""Entry point for `python -m grady`. Fetches jobs from every source and stores the new ones."""

from collections import Counter

from grady import adzuna, reed
from grady.config import load_settings
from grady.storage import JobStore

# Every source has the same fetch_all(term, max_pages, max_days_old) function,
# so adding a source means adding one line here.
SOURCES = {
    "adzuna": adzuna.fetch_all,
    "reed": reed.fetch_all,
}


def main() -> None:
    settings = load_settings()
    search = settings.search
    # Open the database first, so a database problem stops us before we spend API requests.
    store = JobStore()

    all_jobs = []
    for term in search.terms:
        for source_name, fetch_all in SOURCES.items():
            jobs = fetch_all(term, search.max_pages_per_term, search.max_days_old)
            print(f"{source_name:>6} '{term}': {len(jobs)} jobs")
            all_jobs.extend(jobs)

    result = store.save_new(all_jobs)
    print(f"\nFetched {len(all_jobs)} jobs:")
    print(f"  {len(result.new_jobs)} new")
    print(f"  {result.already_seen} already seen on a previous run")
    print(f"  {result.duplicates} duplicates of a job we already have")
    print(f"Database now holds {store.count()} jobs.")
    print(f"New jobs by source: {dict(Counter(job.source for job in result.new_jobs))}")
    print(f"Work mode of new jobs: {dict(Counter(job.work_mode for job in result.new_jobs))}")
    store.close()


if __name__ == "__main__":
    main()
