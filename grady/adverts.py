"""Download a job's full advert text from the same official APIs it came from.

Only used to read what the advert says about visas (grady/visa.py), and only
for jobs that would be emailed, so it's a few requests a day. Adzuna isn't
here: its API gives only the first lines of an advert, and the rest is on
Adzuna's own website, which Grady doesn't scrape. NHS Jobs isn't used now.
"""

import html
import re
from xml.etree import ElementTree

from grady import boards, reed
from grady.config import get_secret
from grady.http_utils import get_with_retries
from grady.models import Job
from grady.ratelimit import RateLimiter

# Sources whose full adverts we can read. Boards reuse their own rate limiters.
SOURCES = {*boards.URLS, "reed"}
_workday_limiter = RateLimiter(min_interval_seconds=boards.WORKDAY_INTERVAL_SECONDS)


class AdvertReader:
    """Reads adverts, remembering whole boards it had to download (Ashby,
    Recruitee and Teamtailor have no "one job" address), so each is downloaded
    at most once per run."""

    def __init__(self):
        self._boards = {}

    def text(self, job: Job) -> str:
        """The advert as plain text ("" if the job is no longer on its board)."""
        token, _, job_id = job.source_id.partition(":")
        if job.source == "reed":
            return plain(self._get(f"https://www.reed.co.uk/api/1.0/jobs/{job.source_id}", "reed",
                                   auth=(get_secret("REED_API_KEY"), "")).json().get("jobDescription"))
        if job.source == "greenhouse":
            return plain(self._get(f"{boards.URLS['greenhouse'].format(token=token)}/{job_id}",
                                   "greenhouse").json()["content"])
        if job.source == "lever":
            data = self._get(f"https://api.lever.co/v0/postings/{token}/{job_id}", "lever").json()
            lists = [f"{item['text']} {item['content']}" for item in data.get("lists", [])]
            return plain(" ".join([data.get("description", ""), *lists, data.get("additional", "")]))
        if job.source == "smartrecruiters":
            data = self._get(f"{boards.URLS['smartrecruiters'].format(token=token)}/{job_id}",
                             "smartrecruiters").json()
            return plain(" ".join(s.get("text", "") for s in data["jobAd"]["sections"].values()))
        if job.source == "workable":
            data = self._get(f"https://apply.workable.com/api/v2/accounts/{token}/jobs/{job_id}",
                             "workable").json()
            return plain(" ".join(data.get(k) or "" for k in ("description", "requirements", "benefits")))
        if job.source == "workday":
            host, site = token.split("/")
            path = job.url.split(".myworkdayjobs.com/", 1)[1][len(site):]  # "/job/..."
            info = get_with_retries(boards.workday_url(token) + path, {}, _workday_limiter,
                                    f"workday advert '{token}'").json()
            return plain(info["jobPostingInfo"]["jobDescription"])
        if job.source == "ashby":
            jobs = self._board(token, "ashby", lambda r: {j["id"]: j for j in r.json()["jobs"]})
            found = jobs.get(job_id) or {}
            return plain(found.get("descriptionPlain") or found.get("descriptionHtml") or "")
        if job.source == "recruitee":
            offers = self._board(token, "recruitee", lambda r: {str(o["id"]): o for o in r.json()["offers"]})
            found = offers.get(job_id) or {}
            return plain(f"{found.get('description') or ''} {found.get('requirements') or ''}")
        if job.source == "teamtailor":
            items = self._board(token, "teamtailor", teamtailor_descriptions)
            return plain(items.get(job.url, ""))
        raise ValueError(f"can't read adverts from {job.source}")

    def _get(self, url, source, auth=None):
        limiter = reed._rate_limiter if source == "reed" else boards._rate_limiters[source]
        return get_with_retries(url, {}, limiter, f"{source} advert", auth=auth)

    def _board(self, token, source, read):
        if (source, token) not in self._boards:
            url = boards.URLS[source].format(token=token)
            self._boards[source, token] = read(self._get(url, source))
        return self._boards[source, token]


def teamtailor_descriptions(response) -> dict[str, str]:
    """{job link: advert} from a Teamtailor RSS feed."""
    channel = ElementTree.fromstring(response.text).find("channel")
    return {item.findtext("link", ""): item.findtext("description", "") for item in channel.iter("item")}


def plain(value: str | None) -> str:
    """HTML to plain text. Some systems escape their HTML twice ("&lt;p&gt;"), so
    entities are decoded before and after removing tags. The end of a paragraph
    or list item becomes a full stop, so grady/visa.py can tell sentences apart."""
    text = re.sub(r"<(br|/p|/li|/h\d|/div)\b[^>]*>", ". ", html.unescape(value or ""), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
