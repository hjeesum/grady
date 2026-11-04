"""Build the public job page: recent sponsor jobs as a web page and an RSS feed.

The files are published with GitHub Pages by the daily workflow. Anyone can see
them, so only sources whose terms allow showing jobs publicly are included:
- Reed: its terms allow copying only "for your own private or domestic purposes",
  so Reed jobs stay in the private email.
- Adzuna: allowed if every job is labelled "Adzuna" with a link to adzuna.co.uk.
- Company boards and Workday: the employers' own public adverts, linked to them.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from grady.config import BOARD_SYSTEMS, PROJECT_ROOT, Profile
from grady.digest import TEMPLATES_DIR, format_salary
from grady.filters import rejection_reason
from grady.models import StoredJob

SITE_DIR = PROJECT_ROOT / "data" / "site"
# An allow-list, not a block-list: a source added later stays off the public
# page until its terms have been checked.
PUBLIC_SOURCES = {"adzuna", *BOARD_SYSTEMS}
DAYS_SHOWN = 14
# GitHub Pages address of this repository (the RSS feed needs a full link to it).
SITE_URL = "https://hjeesum.github.io/grady/"


def public_jobs(stored_jobs: list[StoredJob], profile: Profile) -> list[StoredJob]:
    """The jobs to publish: public sources only, through the profile's filters, newest first."""
    kept = [s for s in stored_jobs
            if s.job.source in PUBLIC_SOURCES and rejection_reason(s.job, profile.filters) is None]
    return sorted(kept, key=lambda s: s.job.posted_at, reverse=True)


def build_site(stored_jobs: list[StoredJob], profile: Profile, now: datetime | None = None,
               out_dir: Path = SITE_DIR, signup_url: str | None = None,
               feedback_url: str | None = None, subscribers: int | None = None) -> int:
    """Write index.html, feed.xml and stats.json to out_dir. Returns how many jobs are on the page."""
    now = now or datetime.now(timezone.utc)
    jobs = public_jobs(stored_jobs, profile)
    # autoescape: job text from APIs can never inject HTML (or break the XML feed).
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    context = {"jobs": jobs, "now": now, "days": DAYS_SHOWN, "profile_name": profile.name,
               "site_url": SITE_URL, "signup_url": signup_url, "feedback_url": feedback_url,
               "format_salary": format_salary}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "feed.xml"):
        (out_dir / name).write_text(env.get_template(f"site_{name}").render(context), encoding="utf-8")
    # Numbers for the README's badges: shields.io reads this file from GitHub Pages,
    # so the badges update every morning without a commit.
    stats = {"jobs": len(jobs), "updated": now.isoformat(timespec="minutes")}
    if subscribers is not None:
        stats["subscribers"] = subscribers
    (out_dir / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    return len(jobs)


def since(now: datetime | None = None) -> datetime:
    """The oldest "first found" time shown on the page."""
    return (now or datetime.now(timezone.utc)) - timedelta(days=DAYS_SHOWN)
