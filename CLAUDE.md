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
6. [ ] Tests (pytest): normalisation, fuzzy matching, de-dup especially.
7. [ ] Email digest: HTML, new sponsor jobs since last run, preferred cities first, cap ~30 + "N more".
8. [ ] GitHub Actions: tests on push, daily scheduled run, secrets via GitHub Secrets.
9. [ ] README: problem, how it works, screenshot, challenges (name matching), future work.

## Layout
- `grady/` — Python package. Run with `python -m grady`.
- `config.yaml` — non-secret settings (committed).
- `.env` — secrets (never committed). `.env.example` lists the variable names.
- `data/` — local runtime files (SQLite db, downloaded sponsor CSV); gitignored.

## Commands (Windows, PowerShell)
- Activate venv: `.venv\Scripts\Activate.ps1`
- Install deps: `pip install -r requirements.txt`
- Run: `python -m grady`
