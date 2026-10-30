"""Download and load the UK Register of Licensed Sponsors (Workers).

The register is published on gov.uk as a CSV whose file name changes with every
update, so we ask the GOV.UK Content API for the current link instead of
hard-coding it.
"""

import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests

from grady.config import PROJECT_ROOT
from grady.normalise import normalise_company

CONTENT_API_URL = (
    "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
)
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "sponsors" / "register.csv"
MAX_AGE = timedelta(days=1)  # the register is updated most working days
TIMEOUT_SECONDS = 60

# Graduate jobs are sponsored on the Skilled Worker route. Other routes (e.g.
# intra-company transfers, religious workers) don't help someone applying from outside.
ROUTE = "Skilled Worker"

# "Everest Kitchen Ltd T/A Gurkha Swindon": an advert might use either name.
TRADING_AS = re.compile(r"\s+(?:t/a|trading as)\s+", re.IGNORECASE)


def find_csv_url() -> str:
    """Ask the GOV.UK Content API for the link to the latest register CSV."""
    response = requests.get(CONTENT_API_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()  # safe here: this URL has no secrets in it
    for attachment in response.json()["details"]["attachments"]:
        if attachment.get("content_type") == "text/csv":
            return attachment["url"]
    raise RuntimeError("No CSV attachment found on the sponsor register page")


def download_register(path: Path = DEFAULT_CSV_PATH) -> Path:
    """Download the register unless we already have a copy from the last day."""
    if path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < MAX_AGE:
            return path

    path.parent.mkdir(parents=True, exist_ok=True)
    # Download to a temporary file first, then rename. If the download fails
    # halfway, we keep the old complete copy instead of a broken half file.
    tmp_path = path.with_suffix(".tmp")
    with requests.get(find_csv_url(), stream=True, timeout=TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp_path.replace(path)
    return path


def load_sponsor_names(path: Path = DEFAULT_CSV_PATH) -> dict[str, str]:
    """Return {normalised name: name as written in the register} for usable sponsors."""
    sponsors = {}
    # utf-8-sig copes with the invisible "byte order mark" some CSV exports start with.
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["Route"].strip() != ROUTE:
                continue
            # B-rated sponsors are on a Home Office action plan and generally
            # can't sponsor new workers until they're back to an A rating.
            if "B rating" in row["Type & Rating"]:
                continue
            original = " ".join(row["Organisation Name"].split())
            for name in TRADING_AS.split(original):
                normalised = normalise_company(name)
                if normalised:
                    sponsors.setdefault(normalised, original)
    return sponsors


if __name__ == "__main__":
    # `python -m grady.sponsors`: download the register and print some checks.
    csv_path = download_register()
    names = load_sponsor_names(csv_path)
    print(f"Loaded {len(names):,} sponsor names from {csv_path.name}")
    for company in ["Accenture (UK) Limited", "Capgemini", "Thales UK Ltd", "Gurkha Swindon"]:
        key = normalise_company(company)
        print(f"  {company!r} -> {key!r}: {names.get(key, 'NOT FOUND (exact match)')}")
