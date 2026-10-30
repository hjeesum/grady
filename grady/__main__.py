"""Entry point for `python -m grady`. Fetches jobs, stores the new ones, checks sponsorship."""

from collections import Counter

import requests

from grady import adzuna, reed
from grady.agencies import AgencyDetector
from grady.classify import classify_company
from grady.config import load_settings
from grady.http_utils import ApiError
from grady.matching import SponsorMatcher
from grady.sponsors import download_register, load_sponsor_names
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
            try:
                jobs = fetch_all(term, search.max_pages_per_term, search.max_days_old)
            except (ApiError, requests.RequestException) as error:
                # One source being down shouldn't cost us the others' jobs. Anything
                # missed is picked up next run, because we ask for several days of jobs.
                print(f"{source_name:>6} '{term}': FAILED ({error}), skipping")
                continue
            print(f"{source_name:>6} '{term}': {len(jobs)} jobs")
            all_jobs.extend(jobs)

    result = store.save_new(all_jobs)
    print(f"\nFetched {len(all_jobs)} jobs:")
    print(f"  {len(result.new_jobs)} new")
    print(f"  {result.already_seen} already seen on a previous run")
    print(f"  {result.duplicates} duplicates of a job we already have")
    print(f"New jobs by source: {dict(Counter(job.source for job in result.new_jobs))}")

    # Check sponsorship for every job not checked yet. This also covers jobs
    # stored before sponsor checking existed.
    companies = store.companies_to_classify()
    if companies:
        agencies = AgencyDetector(settings.known_agencies)
        matcher = SponsorMatcher(load_sponsor_names(download_register()))
        store.set_sponsor_status(
            {company: classify_company(company, agencies, matcher) for company in companies}
        )
    print(f"\nChecked sponsorship for {len(companies)} companies.")
    print(f"Database now holds {store.count()} jobs: {store.count_by_sponsor_status()}")
    store.close()


if __name__ == "__main__":
    main()
