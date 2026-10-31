"""List tech companies on the sponsor register, using Companies House data.

Run from the project root:  python -m scripts.find_tech_sponsors

The sponsor register has ~128,000 names but no industry. Companies House
publishes a free monthly file of every live UK company with its industry (SIC)
codes and accounts category. Joining the two gives tech sponsors that are big
enough to hire graduates; scripts/find_boards.py can then look for their job boards.

The Companies House file is ~470 MB and is downloaded once into data/companies_house/.
Output: data/discovery/tech_sponsors.csv
"""

import csv
import io
import re
import zipfile
from pathlib import Path

import requests

from grady.config import PROJECT_ROOT
from grady.normalise import normalise_company
from grady.sponsors import download_register, load_sponsor_names

DOWNLOAD_PAGE = "https://download.companieshouse.gov.uk/en_output.html"
CH_DIR = PROJECT_ROOT / "data" / "companies_house"
OUTPUT_PATH = PROJECT_ROOT / "data" / "discovery" / "tech_sponsors.csv"

# SIC codes (UK industry codes). 62: computer programming and consultancy;
# 63: data processing, hosting, web portals; 58290: software publishing.
TECH_SIC_PREFIXES = ("62", "63", "58290")

# Accounts categories, from biggest to smallest. Micro, dormant and
# "total exemption" companies are left out: mostly one-person consultancies
# that sponsor a single worker, not graduate employers. (Duffel, which has a
# job board, files "small" accounts, so small stays in.)
SIZE_RANK = {
    "GROUP": 6,
    "FULL": 5,
    "MEDIUM": 4,
    "AUDIT EXEMPTION SUBSIDIARY": 3,  # the UK arm of a bigger group
    "AUDITED ABRIDGED": 2,
    "SMALL": 1,
}

SIC_COLUMNS = ["SICCode.SicText_1", "SICCode.SicText_2", "SICCode.SicText_3", "SICCode.SicText_4"]


def is_tech(sic_texts: list[str]) -> bool:
    """sic_texts look like "62012 - Business and domestic software development"."""
    return any(text.startswith(TECH_SIC_PREFIXES) for text in sic_texts)


def download_companies_house() -> Path:
    """Download this month's Companies House file, unless we already have it."""
    page = requests.get(DOWNLOAD_PAGE, timeout=30)
    page.raise_for_status()
    # The file name has the date in it, e.g. BasicCompanyDataAsOneFile-2026-10-01.zip
    match = re.search(r'href="(BasicCompanyDataAsOneFile-[\d-]+\.zip)"', page.text)
    if not match:
        raise RuntimeError(f"Couldn't find the Companies House file on {DOWNLOAD_PAGE}")
    path = CH_DIR / match.group(1)
    if path.exists():
        return path

    CH_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {path.name} (~470 MB, a few minutes)...")
    tmp = path.with_suffix(".tmp")
    url = DOWNLOAD_PAGE.rsplit("/", 1)[0] + "/" + path.name
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.replace(path)  # only a complete download gets the real name
    return path


def companies(zip_path: Path):
    """Yield each active company as a dict of the columns we need."""
    with zipfile.ZipFile(zip_path) as z, z.open(z.namelist()[0]) as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline=""))
        # Some header names have a leading space, e.g. " CompanyNumber".
        header = [name.strip() for name in next(reader)]
        for row in reader:
            if len(row) != len(header):
                continue  # a handful of malformed rows
            company = dict(zip(header, row))
            if company["CompanyStatus"] == "Active":
                yield company


def main() -> None:
    register = load_sponsor_names(download_register())  # {normalised: register name}
    zip_path = download_companies_house()
    print(f"Reading {zip_path.name} (5.7 million companies, about 3 minutes)...")

    # Several companies can share a normalised name ("Acme Ltd", "Acme UK Ltd").
    # The register doesn't say which one is the sponsor, so keep the biggest tech one.
    found = {}
    in_register = set()
    for company in companies(zip_path):
        key = normalise_company(company["CompanyName"])
        if key not in register:
            continue
        in_register.add(key)
        sics = [company[column] for column in SIC_COLUMNS if company[column]]
        size = SIZE_RANK.get(company["Accounts.AccountCategory"], 0)
        if not is_tech(sics) or size == 0:
            continue
        if key not in found or size > found[key]["size"]:
            found[key] = {
                "register_name": register[key],
                "company_name": company["CompanyName"],
                "company_number": company["CompanyNumber"],
                "accounts": company["Accounts.AccountCategory"],
                "sic": "; ".join(sics),
                "size": size,
            }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(found.values(), key=lambda r: (-r["size"], r["company_name"]))
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(register):,} names on the register; {len(in_register):,} found in Companies House "
          f"({len(in_register) / len(register):.0%}).")
    print(f"{len(rows):,} are tech companies big enough to file full accounts.")
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
