"""Find companies' job boards and check they're worth adding to config.yaml.

Run from the project root:
    python -m scripts.find_boards "Monzo" "Wise" "GoCardless"

For each company it guesses board names ("GoCardless" -> "gocardless"), tries
every system in grady/boards.py, and prints what it finds: how many UK jobs and UK
entry-level jobs the board has, and whether the name matches the sponsor
register. Only add companies that match the register; jobs from the others
would never reach the email anyway.
"""

import re
import sys
from xml.etree import ElementTree

from grady.boards import URLS, fetch_uk_jobs, is_entry_level
from grady.config import load_settings
from grady.http_utils import ApiError
from grady.matching import SponsorMatcher
from grady.sponsors import download_register, load_sponsor_names


def board_names(company: str) -> list[str]:
    """Likely board names: "Go Cardless" -> ["gocardless", "go-cardless"]."""
    words = re.findall(r"[a-z0-9]+", company.lower())
    return list(dict.fromkeys(["".join(words), "-".join(words)]))


def main() -> None:
    companies = sys.argv[1:]
    if not companies:
        sys.exit('Usage: python -m scripts.find_boards "Company Name" ...')

    keywords = load_settings().boards.entry_level_keywords
    matcher = SponsorMatcher(load_sponsor_names(download_register()))

    for company in companies:
        match = matcher.match(company)
        sponsor = f"sponsor: {match.register_name}" if match else "NOT on the register"
        found = False
        for token in board_names(company):
            for ats in URLS:
                try:
                    uk_jobs = fetch_uk_jobs(ats, token, company)
                except (ApiError, ValueError, KeyError, TypeError, ElementTree.ParseError):
                    continue  # no board here (usually HTTP 404), or not the expected JSON
                if ats == "smartrecruiters" and not uk_jobs:
                    # SmartRecruiters answers "no jobs" even for companies it doesn't
                    # know, so an empty answer doesn't mean there's a board.
                    continue
                entry = [job for job in uk_jobs if is_entry_level(job.title, keywords)]
                found = True
                print(f"{company:<25} {ats:<15} token={token:<20} "
                      f"{len(uk_jobs):>3} UK jobs, {len(entry):>2} entry level   ({sponsor})")
                for job in entry[:5]:
                    print(f"{'':<27}- {job.title}")
        if not found:
            print(f"{company:<25} no board found  ({sponsor})")


if __name__ == "__main__":
    main()
