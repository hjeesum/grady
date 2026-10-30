"""Entry point for `python -m grady`.

Fetches jobs, stores the new ones, checks sponsorship, and emails a digest of new jobs.
Run `python -m grady --help` for options.
"""

import argparse
from collections import Counter
from datetime import date

import requests

from grady import adzuna, reed
from grady.agencies import AgencyDetector
from grady.classify import classify_company
from grady.config import PROJECT_ROOT, Settings, load_settings
from grady.digest import build_digest, render_html, render_text, subject
from grady.emailer import send_email
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

PREVIEW_PATH = PROJECT_ROOT / "data" / "digest_preview.html"


def fetch_and_store(store: JobStore, settings: Settings) -> None:
    search = settings.search
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


def classify_unchecked(store: JobStore, settings: Settings) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m grady")
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="don't call the job APIs; build the digest from jobs already stored",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="build the preview but don't send the email or mark jobs as emailed",
    )
    args = parser.parse_args()

    settings = load_settings()
    # Open the database first, so a database problem stops us before we spend API requests.
    store = JobStore()

    if not args.skip_fetch:
        fetch_and_store(store, settings)
    classify_unchecked(store, settings)

    today = date.today()
    digest = build_digest(store.jobs_to_email(), settings)
    html = render_html(digest, settings, today)
    PREVIEW_PATH.write_text(html, encoding="utf-8")
    print(f"\nDigest: {len(digest.sponsor.jobs)} sponsor jobs (+{digest.sponsor.more} more), "
          f"{len(digest.agency.jobs)} agency jobs (+{digest.agency.more} more)")
    print(f"Left out by filters: {dict(digest.filtered_out)}")
    print(f"Preview saved to {PREVIEW_PATH}")

    if args.dry_run:
        print("Dry run: email not sent.")
    elif digest.is_empty:
        # An empty email every day teaches you to ignore the emails.
        print("No new jobs: email not sent.")
    else:
        send_email(subject(digest, today), html, render_text(digest, today))
        # Only mark jobs once the email has definitely gone. If sending fails,
        # send_email raises an error, we never reach this line, and the same
        # jobs are offered again next run.
        store.mark_emailed(digest.reported_ids)
        print(f"Email sent; {len(digest.reported_ids)} jobs marked as emailed.")
    store.close()


if __name__ == "__main__":
    main()
