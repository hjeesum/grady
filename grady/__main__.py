"""Entry point for `python -m grady`. For now it fetches one page from Adzuna."""

from grady import adzuna
from grady.config import load_settings


def main() -> None:
    settings = load_settings()
    term = settings.search.terms[0]

    jobs = adzuna.fetch_page(term, page=1)
    print(f"Adzuna returned {len(jobs)} jobs for '{term}' (page 1):\n")
    for job in jobs[:10]:
        if job.salary_min is not None:
            salary = f"£{job.salary_min:,}-£{job.salary_max:,}"
        else:
            salary = "salary not given"
        print(f"- {job.title} | {job.company} | {job.location} | {salary}")
        print(f"  {job.url}")


if __name__ == "__main__":
    main()
