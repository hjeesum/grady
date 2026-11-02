"""Look for job boards for every company in data/discovery/tech_sponsors.csv.

Also checks the boards scripts/crawl_boards.py found in Common Crawl
(data/discovery/crawl_candidates.csv), if that has been run.

Run from the project root, after scripts/find_tech_sponsors.py:
    python -m scripts.discover_boards                  (every system)
    python -m scripts.discover_boards workable lever   (only these; the others' saved
                                                        answers still count)

For each company it guesses board names, tries every system in grady/boards.py, and
keeps a board only if it has UK jobs AND the company's name appears in its own
adverts (a board called "wise" turned out to be a different company). The
result is written to boards_discovered.yaml, which the daily run reads next to
the hand-checked list in config.yaml.

~45,000 requests the first time: the systems are asked in parallel (Lever, the
slowest, with 4 threads; at most 4 requests a second per thread). Answers are
cached in data/discovery/probe_cache.json, so you can stop it and run it again
to continue.
"""

import csv
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree

import requests

from grady.boards import URLS, PARAMS, is_entry_level, parse_board, read_response, recent_only
from grady.config import PROJECT_ROOT, load_settings
from grady.normalise import normalise_company
from grady.ratelimit import RateLimiter
from grady.sponsors import download_register, load_sponsor_names

INPUT_PATH = PROJECT_ROOT / "data" / "discovery" / "tech_sponsors.csv"
CRAWL_PATH = PROJECT_ROOT / "data" / "discovery" / "crawl_candidates.csv"
CACHE_PATH = PROJECT_ROOT / "data" / "discovery" / "probe_cache.json"
OUTPUT_PATH = PROJECT_ROOT / "boards_discovered.yaml"

REQUEST_INTERVAL_SECONDS = 0.25  # per thread, so at most 4 requests a second each
# Workable refuses more than about one request every 10 seconds (measured Oct 2026:
# ~20 quick answers, then HTTP 429 "too many requests"). Probing it takes ~10 hours,
# so run it on its own, e.g. overnight:  python -m scripts.discover_boards workable
SLOWER_SYSTEMS = {"workable": 12}
# Lever's server takes 1-13 seconds to answer, so the wait is on their side, not
# our rate limit: give it more threads, each working through a share of the companies.
THREADS_PER_SYSTEM = {"greenhouse": 1, "lever": 4, "ashby": 1, "smartrecruiters": 1,
                      "workable": 1, "recruitee": 1, "teamtailor": 1}
TRADING_AS = re.compile(r"\s+(?:t/a|trading as)\s+", re.IGNORECASE)
# Recruitee and Teamtailor put the board name in the web address (name.recruitee.com),
# and one part of an address can be at most 63 characters.
MAX_BOARD_NAME_LENGTH = 63

_cache_lock = threading.Lock()
GAVE_UP = object()  # probe()'s answer when every attempt failed: unlike None, not cached


def board_names(company: str, first_word_counts: Counter) -> list[str]:
    """Likely board names for a company, most likely first.

    "Duffel Technology Ltd" -> ["duffeltechnology", "duffel-technology", "duffel"].

    The first word alone is the riskiest guess: "Quantum Metric" found the board
    of a different company called Quantum. So, like the sponsor matcher's prefix
    rule, we only guess it when exactly one company on the register starts with
    that word (first_word_counts says how many do).
    """
    words = normalise_company(company).split()
    if not words:
        return []
    guesses = ["".join(words), "-".join(words)]
    if len(words) > 1 and len(words[0]) >= 4 and first_word_counts[words[0]] == 1:
        guesses.append(words[0])
    return [g for g in dict.fromkeys(guesses) if len(g) <= MAX_BOARD_NAME_LENGTH]


def count_first_words(register: dict[str, str]) -> Counter:
    """How many register companies start with each word."""
    return Counter(name.split()[0] for name in register)


def name_variants(register_name: str) -> list[str]:
    """Each name a company goes by: "Roofoods Ltd t/a Deliveroo" -> ["roofoods", "deliveroo"]."""
    return [n for n in (normalise_company(part) for part in TRADING_AS.split(register_name)) if n]


def is_same_company(token: str, names: list[str], board_text: str) -> bool:
    """Does the board's own text mention the company?

    The token's words ("thought-machine" -> "thought machine") or one of the
    company's names must appear as whole words in the board's text.
    """
    text = " ".join(board_text.lower().split())
    phrases = [token.replace("-", " ")] + names
    return any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text) for p in phrases)


def board_text(ats: str, data) -> str:
    """The text we search for the company's name."""
    if ats == "greenhouse":
        # Without content=true there are no descriptions, but each job has company_name.
        return " ".join(job.get("company_name") or "" for job in data["jobs"])
    if ats == "smartrecruiters":
        return " ".join(job["company"].get("name") or "" for job in data["content"])
    if ats == "workable":
        return f"{data.get('name') or ''} {data.get('description') or ''}"
    if ats == "recruitee":
        return " ".join(job.get("company_name") or "" for job in data["offers"])
    if ats == "teamtailor":
        return ElementTree.fromstring(data).findtext("channel/title", "")  # the company's name
    postings = data if ats == "lever" else data["jobs"]
    # Lever and Ashby include each job's description; a few jobs are enough.
    return " ".join(
        f"{p.get('descriptionPlain') or ''} {p.get('additionalPlain') or ''}" for p in postings[:5]
    )


def probe(session, limiter, ats: str, token: str):
    """Ask one system for one board.

    Returns the board, None for no board (HTTP 404 or similar), or GAVE_UP when
    every attempt was refused or failed. GAVE_UP isn't saved in the cache: the
    board may well exist, so the next run asks again.
    """
    for attempt in range(3):
        limiter.wait()
        try:
            response = session.get(URLS[ats].format(token=token), params=PARAMS[ats], timeout=30)
        except requests.RequestException:
            time.sleep(5)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(10 * (attempt + 1))  # slow down and retry
            continue
        if response.status_code != 200:
            return None
        try:
            data = read_response(ats, response)
            # Only recent jobs count, so abandoned boards aren't "found".
            return {"data": data, "uk_jobs": recent_only(parse_board(ats, token, "", data))}
        except (ValueError, KeyError, TypeError, AttributeError, ElementTree.ParseError):
            return None  # not the JSON (or RSS) we expect
    return GAVE_UP


def guessed_tokens(register_name: str, first_words: Counter) -> list[str]:
    """Every board name we guess for a company, most likely first."""
    names = name_variants(register_name)
    return list(dict.fromkeys(t for name in names for t in board_names(name, first_words)))


def probe_system(ats: str, boards: list[tuple[str, str]], cache: dict, keywords: list[str]) -> None:
    """Probe (board name, register name) pairs on one system. Runs in its own thread."""
    session = requests.Session()
    limiter = RateLimiter(min_interval_seconds=SLOWER_SYSTEMS.get(ats, REQUEST_INTERVAL_SECONDS))
    gave_up = 0
    for i, (token, register_name) in enumerate(boards, 1):
        key = f"{ats}:{token}"
        if key in cache:
            continue
        found = probe(session, limiter, ats, token)
        if found is GAVE_UP:
            gave_up += 1
            continue
        result = None
        if found is not None:
            uk_jobs = found["uk_jobs"]
            result = {
                "uk_jobs": len(uk_jobs),
                "entry_level": [j.title for j in uk_jobs if is_entry_level(j.title, keywords)],
                "same_company": is_same_company(token, name_variants(register_name),
                                                board_text(ats, found["data"])),
            }
        with _cache_lock:
            cache[key] = result
        if i % 500 == 0:
            print(f"  {ats}: {i}/{len(boards)} board names")
            save_cache(cache)
    if gave_up:
        print(f"  {ats}: {gave_up} names not answered (too many requests?); run again to retry them")


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    # The whole save happens inside the lock: two threads saving at once would
    # both write the same .tmp file, and Windows refuses to replace a file that
    # another thread has open.
    with _cache_lock:
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(CACHE_PATH)


def display_name(register_name: str) -> str:
    """The name to store: the trading name if there is one ("Deliveroo"), else the legal name."""
    return TRADING_AS.split(register_name)[-1].strip()


def read_csv(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def is_good(cache: dict, ats: str, token: str, wrong_boards: list[str]) -> bool:
    """Was this board found, with UK jobs, naming the company, and not marked wrong by hand?"""
    result = cache.get(f"{ats}:{token}")
    return bool(result and result["uk_jobs"] > 0 and result["same_company"]
                and f"{ats}:{token}" not in wrong_boards)


def main() -> None:
    companies = read_csv(INPUT_PATH)
    crawled = read_csv(CRAWL_PATH)
    settings = load_settings()
    keywords = settings.boards.entry_level_keywords
    first_words = count_first_words(load_sponsor_names(download_register()))
    cache = load_cache()
    systems = sys.argv[1:] or list(URLS)
    unknown = set(systems) - set(URLS)
    if unknown:
        sys.exit(f"Unknown systems {sorted(unknown)}. Known: {', '.join(URLS)}")
    print(f"Probing {len(companies):,} companies and {len(crawled):,} Common Crawl boards "
          f"on {', '.join(systems)} ({len(cache):,} answers already cached)...")

    # Each system's (board name -> register name) to ask about: our guesses for
    # every tech sponsor on every system, plus the boards Common Crawl saw.
    to_probe = {ats: {} for ats in systems}
    for company in companies:
        for token in guessed_tokens(company["register_name"], first_words):
            for ats in systems:
                to_probe[ats].setdefault(token, company["register_name"])
    for board in crawled:
        if board["ats"] in to_probe:
            to_probe[board["ats"]].setdefault(board["token"], board["register_name"])

    try:
        with ThreadPoolExecutor(max_workers=sum(THREADS_PER_SYSTEM[s] for s in systems)) as pool:
            futures = [
                # boards[i::n] gives thread i every n-th board name.
                pool.submit(probe_system, ats, boards[i::n], cache, keywords)
                for ats in systems for boards in [list(to_probe[ats].items())]
                for n in [THREADS_PER_SYSTEM[ats]] for i in range(n)
            ]
            for future in futures:
                future.result()  # re-raises any error from the thread
    finally:
        save_cache(cache)  # keep progress even after Ctrl+C or an error

    # One board per company: the first good one in guess order.
    # Skip boards already in config.yaml, and boards found twice (Palantir has two
    # entries on the register: Palantir UK and Palantir Technologies UK).
    # A company found both ways keeps the board from its name guesses.
    wrong = settings.boards.wrong_boards
    seen = {(c.ats, c.token) for c in settings.boards.companies if not c.discovered}
    done_companies = set()
    found = []

    def add(register_name: str, ats: str, token: str) -> None:
        done_companies.add(register_name)
        if (ats, token) not in seen:
            seen.add((ats, token))
            found.append((display_name(register_name), ats, token, cache[f"{ats}:{token}"]))

    for company in companies:
        for token in guessed_tokens(company["register_name"], first_words):
            good = [ats for ats in URLS if is_good(cache, ats, token, wrong)]
            if good:
                add(company["register_name"], max(good, key=lambda a: cache[f"{a}:{token}"]["uk_jobs"]), token)
                break
    for board in crawled:
        if board["register_name"] not in done_companies and is_good(cache, board["ats"], board["token"], wrong):
            add(board["register_name"], board["ats"], board["token"])

    rejected = sum(1 for result in cache.values()
                   if result and result["uk_jobs"] > 0 and not result["same_company"])

    lines = [
        "# GENERATED by `python -m scripts.discover_boards`: don't edit by hand, run it again.",
        "# Job boards of companies on the sponsor register: tech sponsors (found via Companies",
        "# House) and any sponsor whose board is in Common Crawl (scripts/crawl_boards.py).",
        "# Each has UK jobs and mentions the company's name in its own adverts.",
        "# To stop seeing a company, add it to filters.blocked_companies in config.yaml.",
        "companies:",
    ]
    for name, ats, token, result in sorted(found, key=lambda f: f[0].lower()):
        lines.append(f"  - {{name: {json.dumps(name)}, ats: {ats}, token: {token}}}"
                     f"  # {result['uk_jobs']} UK jobs")
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    entry = sum(len(r["entry_level"]) for _, _, _, r in found)
    print(f"\n{len(found)} new boards with UK jobs ({entry} entry-level jobs open now).")
    print(f"{rejected} boards rejected: UK jobs, but the company's name isn't in them.")
    print(f"Saved to {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
