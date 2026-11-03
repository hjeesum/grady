"""Entry point for `python -m grady`.

Fetches jobs for every profile's search terms, stores the new ones, checks
sponsorship, saves a preview digest per profile, and emails your profile's digest.
Run `python -m grady --help` for options.
"""

import argparse
import sys
from collections import Counter
from datetime import date

import requests

from grady import adzuna, boards, nhs_jobs, reed
from grady.agencies import AgencyDetector
from grady.classify import classify_company
from grady.config import PROJECT_ROOT, Settings, load_settings
from grady.digest import build_digest, render_html, render_text, subject
from grady.emailer import send_email
from grady.http_utils import ApiError
from grady.matching import SponsorMatcher
from grady.site import SITE_DIR, build_site
from grady.site import since as site_since
from grady.models import Job
from grady.sponsors import download_register, load_sponsor_names
from grady.storage import JobStore

# Every source has the same fetch_all(term, max_pages, max_days_old) function,
# so adding a source means adding one line here.
SOURCES = {
    "adzuna": adzuna.fetch_all,
    "reed": reed.fetch_all,
    "nhs_jobs": nhs_jobs.fetch_all,
}

PREVIEWS_DIR = PROJECT_ROOT / "data" / "previews"


def fetch_and_store(store: JobStore, settings: Settings) -> list[str]:
    """Fetch from every source and store new jobs. Returns sources that failed every time."""
    search = settings.search
    all_jobs = []
    failures = Counter()
    terms_per_source = {name: settings.terms_for(name) for name in SOURCES}
    for source_name, fetch_all in SOURCES.items():
        terms = terms_per_source[source_name]
        if not terms:
            continue  # no profile uses this source (e.g. nhs_jobs without healthcare)
        print(f"\n{source_name}: {len(terms)} search terms")
        for term in terms:
            try:
                jobs = fetch_all(term, search.max_pages_per_term, search.max_days_old)
            except (ApiError, requests.RequestException) as error:
                # One source being down shouldn't cost us the others' jobs. Anything
                # missed is picked up next run, because we ask for several days of jobs.
                print(f"  '{term}': FAILED ({error}), skipping")
                failures[source_name] += 1
                continue
            print(f"  '{term}': {len(jobs)} jobs")
            all_jobs.extend(jobs)

    board_jobs, boards_failed = fetch_boards(settings)
    all_jobs.extend(board_jobs)

    result = store.save_new(all_jobs)
    print(f"\nFetched {len(all_jobs)} jobs:")
    print(f"  {len(result.new_jobs)} new")
    print(f"  {result.already_seen} already seen on a previous run")
    print(f"  {result.duplicates} duplicates of a job we already have")
    print(f"New jobs by source: {dict(Counter(job.source for job in result.new_jobs))}")

    # Failing for one term is usually a temporary hiccup. Failing for EVERY term
    # usually means a setup problem, like a wrong API key.
    failed = [name for name, count in failures.items() if count == len(terms_per_source[name])]
    return failed + (["company boards"] if boards_failed else [])


def fetch_boards(settings: Settings) -> tuple[list[Job], bool]:
    """Fetch every company board in config.yaml. Returns (jobs, did every board fail?)."""
    companies = settings.boards.companies
    print(f"\ncompany boards: {len(companies)} companies")
    jobs, failed = [], 0
    for company, result in boards.fetch_boards(companies, settings.boards.entry_level_keywords):
        if isinstance(result, Exception):
            # A 404 usually means the company moved to another system or renamed
            # its board: re-run scripts/discover_boards.py (or find_boards).
            print(f"  {company.name}: FAILED ({result}), skipping")
            failed += 1
        elif result:
            print(f"  {company.name}: {len(result)} entry-level UK jobs")
            jobs.extend(result)
    print(f"  {len(jobs)} jobs in total")
    return jobs, bool(companies) and failed == len(companies)


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
    for profile in settings.profiles.values():
        unknown = set(profile.sources) - set(SOURCES)
        if unknown:
            sys.exit(f"config.yaml: profile '{profile.id}' lists unknown sources {sorted(unknown)}. "
                     f"Known sources: {sorted(SOURCES)}")
    # Open the database first, so a database problem stops us before we spend API requests.
    store = JobStore()

    failed_sources = [] if args.skip_fetch else fetch_and_store(store, settings)
    classify_unchecked(store, settings)

    # Build every profile's digest from the same stored jobs, and save each as a
    # preview. (For now only my_profile is emailed; emailed_at tracks that email.)
    today = date.today()
    stored_jobs = store.jobs_to_email()
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    print("\nDigests:")
    digests = {}
    for profile in settings.profiles.values():
        digest = build_digest(stored_jobs, profile, settings.email)
        (PREVIEWS_DIR / f"{profile.id}.html").write_text(render_html(digest, today, settings.feedback_url),
                                                         encoding="utf-8")
        print(f"  {profile.name:<17} {len(digest.sponsor.all_jobs):>3} sponsor jobs, "
              f"{len(digest.agency.all_jobs):>3} agency jobs")
        digests[profile.id] = digest
    print(f"Previews saved in {PREVIEWS_DIR}")

    # The public page shows the last few weeks, emailed or not, so it's built
    # from its own query. Published by the workflow with GitHub Pages.
    shown = build_site(store.sponsor_jobs_since(site_since()), settings.profiles[settings.my_profile],
                       signup_url=settings.signup_url, feedback_url=settings.feedback_url)
    print(f"Public page: {shown} jobs, saved in {SITE_DIR}")

    digest = digests[settings.my_profile]
    html = render_html(digest, today, settings.feedback_url)
    print(f"\nYour email ({digest.profile_name}): left out by filters: {dict(digest.filtered_out)}")
    if args.dry_run:
        print("Dry run: email not sent.")
    elif digest.is_empty:
        # An empty email every day teaches you to ignore the emails.
        print("No new jobs: email not sent.")
    else:
        send_email(subject(digest, today), html, render_text(digest, today, settings.feedback_url))
        # Only mark jobs once the email has definitely gone. If sending fails,
        # send_email raises an error, we never reach this line, and the same
        # jobs are offered again next run.
        store.mark_emailed(digest.reported_ids)
        print(f"Email sent; {len(digest.reported_ids)} jobs marked as emailed.")
    store.close()

    # Finish the run first (email sent, database saved), THEN report the problem.
    # A non-zero exit code makes GitHub Actions mark the run as failed and email you.
    if failed_sources:
        sys.exit(f"\nERROR: {', '.join(failed_sources)} failed every time. "
                 "Check the API key (or, for company boards, the network).")


if __name__ == "__main__":
    main()
