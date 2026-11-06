# Grady — UK visa-sponsor graduate job finder

Portfolio project for a recent CS graduate (international, job hunting in the UK).
Finds graduate/junior tech jobs UK-wide, keeps only employers on the UK Register of
Licensed Sponsors, and emails a daily digest of NEW jobs.

## How to work with this user
- Build in small steps. Stop after each step so they can test and commit (GitHub Desktop).
- Explain every decision; they must be able to defend the code in interviews.
- At the end of each step, list exactly which files to commit and a commit message.
- Official APIs, plus employers' own careers sites read politely (slowly, no logins,
  as robots.txt allows; user chose this for Workday, Nov 2026). Never job sites like
  LinkedIn, Indeed or Glassdoor.

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
       Tech excludes "product owner", "interim" (false positives seen in real data). A max
       salary cap (60k) was tested and rejected: it dropped real junior jobs / top grad pay.
   Original plan: HTML, new sponsor jobs since last run, preferred cities first, cap ~30 + "N more".
8. [x] GitHub Actions: .github/workflows/tests.yml (every push) and daily.yml (no GitHub schedule, only the
       "Run workflow" button). GitHub cron started 7-10 h late, so cron-job.org
       POSTs workflow_dispatch at 06:37 Europe/London (fine-grained token: this repo, Actions
       read/write, 1-year expiry; renew Nov 2027). GitHub cron backup REMOVED (Nov 2026):
       a 2nd daily email to ~209 people came close to Gmail's ~500/day. concurrency group stops double runs. jobs.db persists on a one-commit "data" branch
       of the PRIVATE repo hjeesum/grady-data (secret DATA_REPO_TOKEN: that repo only,
       Contents read/write), because grady goes public and the db holds Reed jobs
       (restored at start, force-pushed at end; a failed restore stops the run so old jobs
       are never re-emailed). Repo hjeesum/grady: going public (Nov 2026).
       Secrets: ADZUNA_APP_ID, ADZUNA_APP_KEY, REED_API_KEY, SMTP_USER, SMTP_PASSWORD, EMAIL_TO,
       SUBSCRIBERS (optional, friends).
9. [x] README.md. Screenshot docs/example_digest.png is from FICTIONAL jobs:
       regenerate with `python -m scripts.make_example_digest`, then screenshot the HTML.
       Keep README numbers in sync if matching/tests change (208 tests, 17/18 correct, 0 wrong).

## Extension: multiple job types and people (started Oct 2026)
User chose: Option B (personal profiles) built "search once, match many", must stay FREE.
Roadmap: (1) profiles [done] -> measure each profile's search terms (needs a fresh
Adzuna day: ~250 requests/day limit) -> (2) [done Nov 2026] public job page + RSS on GitHub Pages (grady/site.py, templates
  site_index.html/site_feed.xml -> data/site/, daily.yml "publish" job; https://hjeesum.github.io/grady/).
  PUBLIC_SOURCES allow-list = adzuna + boards (Reed terms: private use only; NHS unchecked).
  Adzuna terms: label each advert "Adzuna" >= 116x23 px linked to adzuna.co.uk. Sponsor
  jobs only, first found in last 14 days, my_profile filters
-> (3) friends' emails via Google Form + private Sheet, per-recipient sent tracking
-> (4) self-hosting guide in README. Check Adzuna/Reed terms before publishing jobs publicly.
- config.yaml `profiles:` ONLY tech now. User chose (31 Oct 2026) to focus on tech and
  removed healthcare, engineering, finance, law, graduate_schemes (in git history before
  that date; their terms were unmeasured). Profile machinery kept: shared filters +
  per-profile include/exclude/min_salary. `my_profile` = whose digest goes to EMAIL_TO.
  Previews: data/previews/<profile>.html.
- Sources: adzuna, reed (default per profile) + nhs_jobs (public XML feed, Band 5 only,
  healthcare only because its keyword search is loose; code kept, unused now; sources with
  no terms are skipped). Profiles choose via `sources:`.
  NHS org types ("NHS Foundation Trust", "NHS FT", "National Health Service") are
  stripped as legal suffixes in normalise_company. ~250 useful healthcare jobs/week.
- Company boards (grady/boards.py): Greenhouse, Lever, Ashby, SmartRecruiters (asks
  country=gb, pages of 100; unknown company = 200 + empty, not 404), Workable (widget API),
  Recruitee, Teamtailor (RSS). Personio skipped: no country field, mostly German firms.
  New system = URLS/PARAMS/parser in boards.py + config.BOARD_SYSTEMS + discover_boards
  board_text/THREADS_PER_SYSTEM. config.yaml
  `boards.companies` (name = register name, ats, token); not term-based, every open job
  fetched each run, kept if UK + entry-level word in title. source_id = "<token>:<id>".
  Add companies with `python -m scripts.find_boards "Name"`: only add if register match
  AND the board has UK jobs (same token can be another company, e.g. wise/cleo = US firms).
  Use legal names when brands are ambiguous (Elastic -> Elasticsearch). 40 hand-picked
  companies (Wise Payments is on SmartRecruiters; Greenhouse "wise" is a US firm).
  Board jobs posted > 365 days ago are dropped (boards.recent_only): many SmartRecruiters
  boards are abandoned with years-old jobs still "open" (Lyst 2016, Beamery test jobs).
  Workable: ~1 request per 10 s (measured), so daily fetch waits 10 s between its boards
  and discovery probes it separately (`discover_boards workable`, ~10 h, overnight).
- Auto-discovery (user chose; open to scraping, but plan = official data first):
  (a) [done] scripts/find_tech_sponsors.py: register x Companies House free monthly bulk
      file (no API key; ~470 MB in data/companies_house/) -> SIC 62/63/58290 + accounts
      category SMALL or bigger -> data/discovery/tech_sponsors.csv (3,240 companies).
      Finds 27 of the 39 hand-picked; misses fintech (SIC 64/66), R&D labs (72), retail.
  (b) [done] scripts/discover_boards.py probes all of them (threads per system, Lever x4
      because it's slow; cache data/discovery/probe_cache.json) -> boards_discovered.yaml
      (GENERATED, committed, 364 boards on 6 systems before (c); config.py loads it after config.yaml's hand list,
      hand list wins). Accept = UK jobs + company name in board text + first-word guesses
      only when the word is unique on the register. config `boards.wrong_boards` = hand-found
      false matches. Daily fetch: boards.fetch_boards, one thread per system, Workday x8 (~12 min),
      Workable ~25 min (10 s per board). 1,003 boards incl. 121 Workday, 152 Workable (Nov 2026).
  (c) [done, Nov 2026] scripts/crawl_boards.py: Common Crawl index (3 newest monthly
      crawls, one query per system URL pattern, cache data/discovery/crawl_cache.json;
      server often 502/504 or cuts answers off -> retries) lists ~20,000 existing boards
      -> matched against the WHOLE register (not just tech SICs) -> crawl_candidates.csv
      -> discover_boards checks them too (2nd input). First-word matches only when the
      rest of the name is generic (crawl_boards.GENERIC_WORDS; "crusoe" = Crusoe Inns).
      Added 333 boards (697 discovered). 12 doubtful one-word clashes in wrong_boards:
      user rule = when unsure, leave out (non-sponsor shown as sponsor is worse).
      New ATS = add a PATTERNS entry too (test checks PATTERNS == URLS).
      Workable [done, Nov 2026]: guessing all names = 6,297 x 12 s = ~21 h and got the IP blocked,
      so Workable is CRAWL_ONLY too: 419 crawled boards (~1.5 h) -> 152 kept
      (ics, trivium, jove in wrong_boards: can't prove same company).
  (d) [done, Nov 2026] Workday (branch `workday`): CXS JSON API, POST
      {host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs; token = "host/site".
      Not guessable (CRAWL_ONLY): found only via Common Crawl (its count query
      always 504s -> read pages until empty). Daily fetch searches WORKDAY_SEARCHES
      (6 terms), looks up details only when the list location isn't clearly UK.
      WORKDAY_THREADS = 8, each site its own 0.5 s limiter (1 thread took 54 min).
      Discovery counts UK jobs from the location filters (one request) + 1 detail
      request for company-name text. Wrong matches + internal-only sites in
      wrong_boards; 5 renamed to the right register company in the hand list
      (hand list wins by ats+token). Barclays/BlackRock hand-added (first word clashes).
  Location bug found via Workday (Nov 2026): US towns named after UK ones
  ("Manchester, CT", "US - Massachusetts - Cambridge") counted as UK; is_uk_location
  now drops "Town, STATE" parts and needs a UK word when a US word appears.
  Workable blocked the home IP for ~16 h (Retry-After 58690) after a long probe;
  discover_boards now stops a system on a long Retry-After and saves every 50 answers.
  fetch_boards: one board's KeyError/ValueError/TypeError = that board's error only.
  Tried and rejected (Nov 2026): website discovery (guess domain, prove it by the company
  number shown on the site, follow Careers link): 10/50 sites, 0 new boards. Wikidata has
  websites for only 65/3,240. Never scrape Google for websites.
  Later options discussed: job-alert emails (LinkedIn etc. without scraping; plan = IMAP
  with the existing Gmail app password + a Gmail label, not the Gmail API, whose personal
  OAuth tokens can expire weekly).
  Never scrape LinkedIn/Indeed: no official LinkedIn search API exists, paid "LinkedIn
  APIs" are scrapers, and the user's own account could be banned.
- Friends (Nov 2026, user chose: friends send their address, user adds it): optional secret
  SUBSCRIBERS (commas/new lines) -> same digest (emailer.parse_subscribers).
  Nov 2026: Bcc replaced by ONE EMAIL PER PERSON (To = them, 1 s apart, one SMTP session,
  reconnect once on disconnect; refused address = skipped; SMTPDataError = Gmail daily limit
  -> stop; owner's copy failing raises so nothing is marked). Failures -> run exits non-zero
  AFTER marking. Unsubscribe button: link = script URL ?action=unsubscribe&email&token,
  token = HMAC-SHA256(key from SIGNUP_LIST_URL, address); script confirms ("Yes" link, because
  scanners open links), deletes their rows, logs them in an "Unsubscribed" tab; list output
  has "-address" lines so SUBSCRIBERS entries are dropped too. Also List-Unsubscribe header.
  Owner's own copy: no link, footer "reply to stop".
  Addresses only in GitHub Secrets / .env. emailed_at is shared,
  fine while everyone gets the one tech digest; per-recipient table only if profiles differ.
  Sign-up: config.yaml site.signup_url = Google Form (answers private to the user) ->
  "Get them by email" button on the page. Form collects VERIFIED emails (Google sign-in: no
  signing up strangers from the user's Gmail). Answers Sheet + Apps Script web app
  (scripts/signup_sheet.gs, key in Script Properties) -> secret SIGNUP_LIST_URL (url?key=...)
  -> emailer.signed_up, merged with SUBSCRIBERS. A broken list only warns, never stops the
  email. Unsubscribe = delete the row in the Sheet (or the SUBSCRIBERS entry).
  Feedback: config.yaml site.feedback_url (another Google Form) -> "Send feedback" link in
  the email footer (HTML + text) and the page footer.
  Subscriber COUNT (never addresses: Actions logs are public) is logged each run and
  published in data/site/stats.json -> shields.io dynamic badges in the README.
  208 form sign-ups on 4 Nov 2026: watch Gmail sending limits (each email = 1 + N recipients).

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
