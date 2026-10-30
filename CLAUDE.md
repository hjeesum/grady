# Grady — UK visa-sponsor graduate job finder

Portfolio project for a recent CS graduate (international, job hunting in the UK).
Finds graduate/junior tech jobs UK-wide, keeps only employers on the UK Register of
Licensed Sponsors, and emails a daily digest of NEW jobs.

## How to work with this user
- Build in small steps. Stop after each step so they can test and commit (GitHub Desktop).
- Explain every decision; they must be able to defend the code in interviews.
- At the end of each step, list exactly which files to commit and a commit message.
- Official APIs only, no scraping.

## Plan (mark steps done as they land)
1. [x] Setup: venv, requirements.txt, `.env` for secrets (gitignored, `.env.example` committed),
       `config.yaml` for settings, `grady/config.py` loader.
2. [x] Fetcher: Adzuna + Reed (pagination, rate limit, retries in http_utils.py).
       Reed locations are often postcodes -> converted to place names via postcodes.io.
3. [x] Storage: SQLite (title, company, location, remote/hybrid, salary, link, source, date found).
4. [x] De-duplication across pages and sources: normalised company + title, locations sharing a part.
   - Not yet built: applying config filters (exclude_keywords, min_salary); search also returns
     non-tech graduate jobs (consider Adzuna `category=it-jobs`).
   - Many Reed adverts are from recruitment agencies (Itol Recruit, Penguin Recruitment, Noir),
     which hide the real employer. Decide how to handle these in step 5.
5. [x] Sponsor matching. Each job gets sponsor_status "sponsor" / "agency" / "not_sponsor".
       Agencies (keywords + config.yaml known_names) are checked BEFORE sponsor matching;
       user chose: show agency jobs in a separate "check sponsorship yourself" email section.
       DB schema changes go through MIGRATIONS in storage.py (don't make the user delete the db).
       Matcher = exact -> unique word-prefix -> rapidfuzz ratio >= 95. Re-check with
       `python -m scripts.evaluate_matching` after any matching change. Stripping generic
       words was tried and made results worse (e.g. Express Solicitors = Express Solutions).
   Original plan: gov.uk Register of Licensed Sponsors (Workers) CSV, normalise names
       (lowercase, strip Ltd/Limited/PLC...), rapidfuzz with a tested threshold.
6. [x] Tests (pytest): normalisation, matching, de-dup, storage/migration, agencies, parsing.
       The labelled-set test only runs when data/sponsors/register.csv exists.
7. [x] Email: filters.py + digest.py + templates/digest.html + emailer.py (SMTP, HTML + text).
       Preview always at data/digest_preview.html. `--skip-fetch` (no API calls), `--dry-run`
       (no send, no marking). emailed_at is set only after a successful send, for shown and
       "...and N more" jobs; filtered-out jobs stay unmarked.
       Search terms chosen by measurement (Oct 2026): useful sponsor tech jobs/week went 4 -> 14.
       Adzuna category=it-jobs was tested and rejected: it hides graduate schemes.
       filters.blocked_companies (ITOL Recruit) hides a company entirely.
   Original plan: HTML, new sponsor jobs since last run, preferred cities first, cap ~30 + "N more".
8. [x] GitHub Actions: .github/workflows/tests.yml (every push) and daily.yml (07:00 UTC +
       manual "Run workflow" button). jobs.db persists on a one-commit "data" branch
       (restored at start, force-pushed at end). Repo hjeesum/grady is private.
       Secrets: ADZUNA_APP_ID, ADZUNA_APP_KEY, REED_API_KEY, SMTP_USER, SMTP_PASSWORD, EMAIL_TO.
9. [x] README.md. Screenshot docs/example_digest.png is from FICTIONAL jobs:
       regenerate with `python -m scripts.make_example_digest`, then screenshot the HTML.
       Keep README numbers in sync if matching/tests change (88 tests, 17/18 correct, 0 wrong).

## Extension: multiple job types and people (started Oct 2026)
User chose: Option B (personal profiles) built "search once, match many", must stay FREE.
Roadmap: (1) profiles [done] -> measure each profile's search terms (needs a fresh
Adzuna day: ~250 requests/day limit) -> (2) public job pages + RSS on GitHub Pages
-> (3) friends' emails via Google Form + private Sheet, per-recipient sent tracking
-> (4) self-hosting guide in README. Check Adzuna/Reed terms before publishing jobs publicly.
- config.yaml `profiles:` tech, healthcare, engineering, finance, law, graduate_schemes,
  all entry level. Shared filters + per-profile include/exclude/min_salary.
  `my_profile` = whose digest goes to EMAIL_TO. Previews: data/previews/<profile>.html.
- Only tech terms are measured; the other profiles' terms are unmeasured starting points.
- emailed_at still tracks only my_profile's email; friends need a per-recipient table.

## Layout
- `grady/` — Python package. Run with `python -m grady`.
- `config.yaml` — non-secret settings (committed).
- `.env` — secrets (never committed). `.env.example` lists the variable names.
- `data/` — local runtime files (SQLite db, downloaded sponsor CSV); gitignored.

## Commands (Windows, PowerShell)
- Activate venv: `.venv\Scripts\Activate.ps1`
- Install deps: `pip install -r requirements-dev.txt` (includes pytest)
- Run: `python -m grady`
- Test: `python -m pytest`
- Re-check sponsor matching: `python -m scripts.evaluate_matching`
