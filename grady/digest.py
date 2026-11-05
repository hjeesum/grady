"""Build the daily email: choose, order and cap the jobs, then render HTML."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from grady.config import EmailSettings, Profile
from grady.filters import rejection_reason
from grady.models import Job, StoredJob
from grady.normalise import same_location

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class Section:
    all_jobs: list[StoredJob]  # every job for this section, in display order
    cap: int  # how many to show

    @property
    def jobs(self) -> list[StoredJob]:
        """The jobs shown in the email."""
        return self.all_jobs[:self.cap]

    @property
    def more(self) -> int:
        """How many jobs beyond the cap ("...and N more")."""
        return max(0, len(self.all_jobs) - self.cap)


@dataclass
class Digest:
    profile_name: str  # e.g. "Tech"
    preferred_cities: list[str]  # marked with a star in the email
    sponsor: Section
    agency: Section
    filtered_out: Counter  # reason -> number of jobs left out for that reason

    @property
    def is_empty(self) -> bool:
        return not self.sponsor.jobs and not self.agency.jobs

    @property
    def reported_ids(self) -> list[int]:
        """Every job the email tells you about: shown, or counted in "...and N more".

        Filtered-out jobs aren't included, so if you loosen a filter they still
        appear in a later email.
        """
        return [s.id for s in self.sponsor.all_jobs + self.agency.all_jobs]


def build_digest(stored_jobs: list[StoredJob], profile: Profile, email: EmailSettings) -> Digest:
    filters = profile.filters
    kept = []
    filtered_out = Counter()
    for stored in stored_jobs:
        reason = rejection_reason(stored.job, filters)
        if reason:
            filtered_out[reason] += 1
        else:
            kept.append(stored)

    def sort_key(stored: StoredJob):
        job = stored.job
        if is_preferred_city(job, filters.preferred_cities):
            group = 0
        elif job.work_mode == "remote" and filters.remote_ok:
            group = 1
        else:
            group = 2
        # Within each group, newest first (a negative timestamp sorts newest first).
        return (group, -job.posted_at.timestamp())

    def section(status: str, cap: int) -> Section:
        jobs = sorted((s for s in kept if s.sponsor_status == status), key=sort_key)
        return Section(all_jobs=jobs, cap=cap)

    return Digest(
        profile_name=profile.name,
        preferred_cities=filters.preferred_cities,
        sponsor=section("sponsor", email.max_sponsor_jobs),
        agency=section("agency", email.max_agency_jobs),
        filtered_out=filtered_out,
    )


def is_preferred_city(job: Job, preferred_cities: list[str]) -> bool:
    return any(same_location(job.location, city) for city in preferred_cities)


def format_salary(job: Job) -> str:
    if job.salary_min is None and job.salary_max is None:
        return "Salary not given"
    low = job.salary_min or job.salary_max
    high = job.salary_max or job.salary_min
    if low == high:
        return f"£{low:,}"
    return f"£{low:,} – £{high:,}"


def subject(digest: Digest, today: date) -> str:
    count = len(digest.sponsor.all_jobs)
    return (f"Grady {digest.profile_name}: {count} new sponsor job{'s' if count != 1 else ''}"
            f" – {today:%d %b %Y}")


def render_html(digest: Digest, today: date, feedback_url: str | None = None,
                unsubscribe_url: str | None = None) -> str:
    # autoescape=True turns characters like < and & in job data into safe HTML,
    # so text from an API can never break or inject into the email.
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("digest.html")
    return template.render(
        digest=digest,
        subject=subject(digest, today),
        today=today,
        feedback_url=feedback_url,
        unsubscribe_url=unsubscribe_url,
        format_salary=format_salary,
        is_preferred=lambda job: is_preferred_city(job, digest.preferred_cities),
    )


def render_text(digest: Digest, today: date, feedback_url: str | None = None,
                unsubscribe_url: str | None = None) -> str:
    """Plain-text version of the email, for programs that don't show HTML."""
    lines = [subject(digest, today), ""]
    sections = [
        ("LICENSED SPONSORS", digest.sponsor),
        ("RECRUITMENT AGENCIES: check sponsorship yourself", digest.agency),
    ]
    for heading, section in sections:
        if not section.jobs:
            continue
        lines += [heading, ""]
        for stored in section.jobs:
            job = stored.job
            lines += [
                job.title,
                f"  {job.company} · {job.location or 'Location not given'} · {format_salary(job)}",
                f"  {job.url}",
                "",
            ]
        if section.more:
            lines += [f"...and {section.more} more.", ""]
    lines.append("Always confirm sponsorship with the employer before applying.")
    if unsubscribe_url:
        lines.append(f"Unsubscribe: {unsubscribe_url}")
    else:
        lines.append("To stop these emails, reply and say so.")
    if feedback_url:
        lines.append(f"Ideas or problems? Send feedback: {feedback_url}")
    return "\n".join(lines)
