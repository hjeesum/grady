"""Find job boards of sponsors using Common Crawl, a free public copy of the web.

Run from the project root, then scripts/discover_boards.py to check what it found:
    python -m scripts.crawl_boards

scripts/discover_boards.py guesses board names for the ~3,200 tech sponsors and
asks each system whether they exist (~45,000 requests, mostly "no"). This works
the other way round: Common Crawl's index lists every address it saved, so one
query per system ("every address starting with jobs.lever.co/") gives us the
boards that DO exist. Their names are then matched against the whole sponsor
register (~128,000 companies, not only the tech ones), so banks, defence and
other firms that hire developers are found too.

A match is only a candidate: discover_boards.py still checks each board has UK
jobs and names the company in its own adverts.

Each monthly crawl saves only part of the web, so we read the newest few.
Answers are cached in data/discovery/crawl_cache.json; run it again to continue.
Output: data/discovery/crawl_candidates.csv
"""

import csv
import json
import re
import time
from collections import defaultdict

import requests

from grady.boards import URLS
from grady.config import PROJECT_ROOT
from grady.ratelimit import RateLimiter
from grady.sponsors import download_register, load_sponsor_names
from scripts.discover_boards import board_names, count_first_words, name_variants

COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
CACHE_PATH = PROJECT_ROOT / "data" / "discovery" / "crawl_cache.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "discovery" / "crawl_candidates.csv"

CRAWLS_TO_READ = 3  # the newest monthly crawls; older ones have more closed boards

# For each system: the addresses to ask Common Crawl for, and how to get the
# board name out of one. "*.x.com" means any address on any part of x.com.
PATTERNS = {
    "greenhouse": (["boards.greenhouse.io/*", "job-boards.greenhouse.io/*"],
                   # also the embedded form: boards.greenhouse.io/embed/job_board?for=monzo
                   r"greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)"),
    "lever": (["jobs.lever.co/*"], r"jobs\.lever\.co/([a-z0-9_.-]+)"),
    "ashby": (["jobs.ashbyhq.com/*"], r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)"),
    "smartrecruiters": (["jobs.smartrecruiters.com/*", "careers.smartrecruiters.com/*"],
                        r"smartrecruiters\.com/([a-z0-9_-]+)"),
    "workable": (["apply.workable.com/*"], r"apply\.workable\.com/([a-z0-9_-]+)"),
    "recruitee": (["*.recruitee.com"], r"//([a-z0-9-]+)\.recruitee\.com"),
    "teamtailor": (["*.teamtailor.com"], r"//([a-z0-9-]+)\.teamtailor\.com"),
}

# A board named after only the first word of a sponsor ("airwallex" for
# "Airwallex (UK) Limited") is accepted only if the other words say nothing about
# what the company does. Across the whole register, "crusoe" otherwise matched
# Crusoe Inns (pubs) to the board of Crusoe, a US cloud firm.
GENERIC_WORDS = {"uk", "ai", "software", "technology", "technologies", "tech", "labs", "lab",
                 "analytics", "hq", "group", "global", "international", "europe", "european",
                 "holdings", "systems", "digital", "io", "bio"}

# The index server is busy and often answers 502/504; Common Crawl asks for one
# request at a time and slowing down when that happens.
_limiter = RateLimiter(min_interval_seconds=1)


def board_token(ats: str, url: str) -> str | None:
    """The board name in a saved address, e.g. "https://jobs.lever.co/palantir/6ed7" -> "palantir"."""
    match = re.search(PATTERNS[ats][1], url, re.IGNORECASE)
    return match.group(1).lower() if match else None


def ask_index(session, crawl: str, params: dict) -> str | None:
    """One index request, retried with longer and longer waits. None if it never answered."""
    for attempt in range(6):
        _limiter.wait()
        try:
            response = session.get(f"https://index.commoncrawl.org/{crawl}-index",
                                   params=params, timeout=120)
            if response.status_code == 200:
                return response.text
            if response.status_code == 404:  # "no captures": nothing saved for this address
                return ""
        except requests.RequestException:
            pass
        time.sleep(10 * (attempt + 1))
    return None


def tokens_in_crawl(session, crawl: str, ats: str, pattern: str) -> list[str] | None:
    """Every board name one crawl saved for one address pattern. None if a page failed."""
    info = ask_index(session, crawl, {"url": pattern, "output": "json", "showNumPages": "true"})
    if info is None:
        return None
    pages = json.loads(info)["pages"] if info else 0
    tokens = set()
    for page in range(pages):
        urls = page_urls(session, crawl, {"url": pattern, "output": "json", "fl": "url", "page": page})
        if urls is None:
            return None  # not cached, so the next run asks again
        tokens.update(t for t in (board_token(ats, url) for url in urls) if t)
    return sorted(tokens)


def page_urls(session, crawl: str, params: dict) -> list[str] | None:
    """The addresses on one page of results. None if it never came back whole."""
    for _ in range(3):
        text = ask_index(session, crawl, params)
        if text is None:
            return None
        try:
            return [json.loads(line)["url"] for line in text.splitlines()]
        except ValueError:
            pass  # the server sometimes cuts an answer off mid-line: ask again
    return None


def match_register(tokens: dict[str, set[str]], register: dict[str, str]) -> tuple[list[tuple], int]:
    """Board names that are a sponsor's likely board name (the same guesses as discover_boards).

    Returns ([(register name, ats, token)], how many names fit more than one sponsor).
    Those are skipped: we couldn't tell which company the board belongs to.
    """
    first_words = count_first_words(register)
    owners = defaultdict(set)  # board name -> sponsors it could belong to
    for original in register.values():
        for name in name_variants(original):
            first, *rest = name.split()
            for guess in board_names(name, first_words):
                if guess == first and not set(rest) <= GENERIC_WORDS:
                    continue
                owners[guess].add(original)
    found, ambiguous = [], 0
    for ats, names in tokens.items():
        for token in sorted(names):
            if len(owners.get(token, ())) > 1:
                ambiguous += 1
            elif token in owners:
                found.append((next(iter(owners[token])), ats, token))
    return found, ambiguous


def main() -> None:
    session = requests.Session()
    crawls = [c["id"] for c in session.get(COLLINFO_URL, timeout=60).json()[:CRAWLS_TO_READ]]
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    print(f"Reading {', '.join(crawls)} ({len(cache)} answers already cached)...")

    tokens = defaultdict(set)
    failed = 0
    for ats, (patterns, _) in PATTERNS.items():
        for crawl in crawls:
            for pattern in patterns:
                key = f"{crawl} {pattern}"
                if key not in cache:
                    answer = tokens_in_crawl(session, crawl, ats, pattern)
                    if answer is None:
                        failed += 1
                        continue
                    cache[key] = answer
                    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
                tokens[ats].update(cache[key])
        print(f"  {ats}: {len(tokens[ats]):,} boards")

    found, ambiguous = match_register(tokens, load_sponsor_names(download_register()))
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["register_name", "ats", "token"])
        writer.writerows(found)

    print(f"\n{len(found):,} boards named like a sponsor ({ambiguous} skipped: fit more than one sponsor).")
    print(f"Saved to {OUTPUT_PATH.relative_to(PROJECT_ROOT)}. "
          "Next: python -m scripts.discover_boards greenhouse lever ashby ...")
    if failed:
        print(f"{failed} queries got no answer (the index server is busy); run again to retry them.")


if __name__ == "__main__":
    main()
