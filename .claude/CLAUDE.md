# research_feed (litfeed)

A literature-surfacing system: Semantic Scholar feeds recreated from hand-curated seed lists
(the S2 website's feeds have no API), triaged against a researcher's taste profile, with
reading notes for papers worth reading, a local rating UI, a BibTeX library, and deep dives
for new projects.

## Code and data

This checkout is the public framework. Everything personal lives in the **data directory**
(`litfeed.paths.DATA_ROOT`: `$LITFEED_DATA`, else `data/` here, which is gitignored and is
usually its own private git repo): `configs/feeds.yaml`, `seeds/`, `taste/` (profile and
ratings), `fetches/`, `triage/`, `digests/`, `notes/`, `projects/`, `state/`, `library/`,
`cache/`, `logs/`, and `.env`. Paths below are relative to it unless they name code
(`scripts/`, `src/`, `prompts/`, `tests/`, `examples/`). `scripts/init_data.py` creates a data
directory from `examples/`. Keep personal details (names, IDs, project specifics) out of this
repo: tests use `tests/fixtures/data` (set by `tests/conftest.py`), never the real data.

The data directory's own notes, if present (the user's status, feeds, and open items):
@../data/CLAUDE.md

## Pipeline

Weekly pipeline (each step a script; run in order):
1. `scripts/fetch_recommendations.py` → `fetches/<date>.jsonl` (gitignored): POST
   recommendations per feed (pool is effectively ~2 months of recent papers; no `from` param),
   papers citing the user, and recent papers by `flagged_authors`. Seeds = curated
   `seeds/<feed>.tsv` + learned from ratings (user tier 1 → positive, user tier 4 → negative,
   for each seed feed that surfaced the paper; `litfeed.ratings.feedback_seeds`). Filters
   seeds/excluded/seen.
2. `scripts/triage.py fetches/<date>.jsonl` → `triage/<date>.jsonl`: arXiv abstract backfill,
   duplicate-version merge by normalized title, flagged-author tagging, then batches of 25 to
   `claude -p --bare --json-schema` with `prompts/triage.md` + `taste/profile.md` + calibration
   examples (rating corrections and notes) as system prompt. `--bare` isolates the run from
   CLAUDE.md/memory/hooks and bills ANTHROPIC_API_KEY. First run: 323 papers, ~$0.82 Sonnet.
3. `scripts/summarize.py triage/<date>.jsonl` → `notes/<paperId>.md` for tier 1 (`--max-tier`
   to widen): full text from arXiv LaTeX source (comments stripped) → open-access PDF via
   `pdftotext` → abstract; one `claude -p --bare --tools ""` call per paper with
   `prompts/summarize.md`. First run: 18 notes, ~$2.35 Sonnet. Downloads are extracted with
   tarfile's `data` filter into `cache/fulltext/` and never executed.
4. `scripts/render_digest.py triage/<date>.jsonl` → read-only `digests/<date>.md` archive, and
   appends to `state/seen.tsv` (only triaged papers, so a paper that got no judgment resurfaces).
Steps 1-4 run unattended via `scripts/weekly.sh` (launchd job `local.litfeed.weekly`,
   Wednesdays 11:00 local; plist template in `configs/launchd/`, install/uninstall with
   `scripts/install_weekly.sh`, which bakes `LITFEED_DATA` into the plist). It reads the API
   keys and `LITFEED_PYTHON` from `.env` (launchd skips `~/.zshrc`),
   caps notes at 10 (`summarize.py --max-papers`), logs to `logs/weekly-<date>.log`, and posts a
   macOS notification on success or failure. It skips if `triage/<today>.jsonl` exists. Missed
   runs (Mac asleep) fire once on wake. Nothing is committed automatically.
5. `scripts/serve_ui.py` → local UI at 127.0.0.1:8765 (`litfeed.web`: `server.py` + `static/`
   CSS/JS, shared helpers in `common.js`). Digest pages: collapsible tiers, reading notes,
   per-paper tier dropdown + note box that autosave to `taste/ratings.jsonl` (append-only,
   latest per paper wins; blank tier = no opinion, not agreement). Project pages
   (`/project/<slug>`): the deep-dive synthesis with `[n]` citations linked to paper cards,
   papers by relevance, and 👍/👎 per paper (`litfeed.projects.set_thumb` →
   `projects/<slug>/thumbs.jsonl`): 👍 adds the paper to the feed named in
   `projects/<slug>/project.yaml`, 👎 removes it, neutral undoes the previous thumb's own
   change (never removes a seed it didn't add; restores a row it removed). 👍 also saves to the
   library when the toolbar toggle is on (default on, remembered in localStorage; 👎/neutral
   never unsave). JS checks: parse with JXA, and `tests/js/run_ui_smoke.sh` runs the project
   page against a fake DOM with fixture data and simulated clicks (JXA only settles promises after
   the script ends, so results print via console.log). No real-browser test.
   Management (`litfeed.web.manage`, routes in `ROUTES`): `/feeds` lists each feed's seeds
   (remove ✕, Save, "+ Add papers" via `litfeed.resolve`: S2/arXiv/DOI/ACL links or IDs, else
   S2 title match, confirmed by the user before writing), flagged authors (S2 author search,
   tick every split profile), and a new-feed form whose seeds can mix ticked seeds, pasted
   identifiers, a project's `seeds.tsv` (optionally linking the project), and a library
   collection. `configs/feeds.yaml` is edited with ruamel.yaml round-tripping
   (`litfeed.config_edit`), which keeps comments; a new feed is appended to `feeds:` with the
   trailing comment block moved below it. `/deepdive/new` writes `projects/<slug>/description.md`
   verbatim (the skill distills it; the UI doesn't) and starts the search stage via
   `litfeed.jobs` (one job at a time, status/log in `logs/jobs/<slug>.{json,log}`, stages in the
   server's process group so stopping the server interrupts them; the page offers resume). The
   project page then polls progress, shows the seed checkpoint (proposed core papers ticked, 40
   best-supported related papers unticked), writes `seeds.tsv`, and runs recommend → notes
   (top 15) → synthesize. `tests/js/run_manage_smoke.sh` covers these pages with scenarios in
   `tests/js/scenarios/`.

6. Library (from the UI's ☆ Save button, separate from rating on purpose: saving means "keep
   this reference", not "more like this", so it never creates seeds): `litfeed.library` appends
   BibTeX to `library/<collection>.bib` (collections = seed feeds + `general`; default is the
   feed where the paper ranked best), records `library/index.tsv`, and downloads the PDF to
   `library/pdfs/<key>.pdf` (gitignored). BibTeX source order: ACL Anthology → DOI content
   negotiation (non-arXiv DOIs; reformatted to one field per line) → arXiv → S2
   `citationStyles` → minimal generated @misc. Keys are made unique library-wide with a b/c/...
   suffix. Unsave removes the entry (PDF kept); changing the collection moves it.

How feedback flows back: ratings → feedback seeds (fetch) and calibration examples (triage).
Not yet: profile refinement from ratings; papers surfaced only by `citing_me`/`flagged_authors`
don't become seeds because they have no feed to attach to.

Not built yet: agreement report (predicted vs. user tier) and periodic profile refinement from
ratings (show the diff to the user).

Known quirks: the first digest's `citing_me` set is the full citation backlog, not just new
papers; undated papers by flagged authors pass the 60-day window; S2 author profiles can mix
in other people's papers; the UI's JavaScript is tested only against a fake DOM (JXA).

## Setup page

`/setup` (`litfeed.web.onboarding` + `static/setup.js`, logic in `litfeed.setup`) is the
first-run checklist; `scripts/serve_ui.py` creates the data directory on start
(`setup.init_data_dir`), loads `.env` into the process, and opens /setup until
`setup_status()["ready"]` (Anthropic key + `claude` CLI + a non-template profile + one seeded
feed). Steps: keys saved to `.env` (mode 600; tested via S2 search and the `anthropic` SDK's
free `models.list`), S2 author ID (`config_edit.set_author_id`), a profile drafted by one
`claude -p` call from the author's recent abstracts plus the user's notes
(`prompts/profile_draft.md`, ~$0.03), seed bootstrap (`seed_from_author.py` as job
`setup-seeds`, then tick candidates into a feed; the first feed replaces the template's
unused `example_feed`), launchd schedule (`setup.install_schedule`, plistlib; one job per user,
so status flags a job installed for another data directory), and a first run (`weekly.sh` as
job `weekly`). **Weekly automation is macOS-only** (launchd, osascript); keep the README's
platform note in sync if that changes.

The server rejects non-localhost `Host` headers and non-same-origin or non-JSON POSTs
(`UIHandler._trusted`); keep every new endpoint behind it. Job status files are written
atomically (`jobs._write_status`) because pages poll them while jobs write.

## Conventions

- Per-feed `seeds/*.tsv` are curated data: never regenerate or overwrite them from a script;
  propose additions/removals as a diff for the user to approve. The only other writers are the
  UI's explicit user actions (👍/👎 on project pages, the /feeds page).
- `seeds/candidates.tsv` and `seeds/citing_me.tsv` are generated and may be overwritten.
- Verify S2 endpoint names/parameters against the official docs before relying on them
  (`https://api.semanticscholar.org/{graph,recommendations}/v1/swagger.json` is machine-readable;
  the HTML docs pages don't render for fetch tools).
- Do not send the user's name or other personal details to external services; use the S2
  author ID in `configs/feeds.yaml`.
- Python style: Google docstrings, 100-char lines (`ruff check --select F,E9,E501
  --line-length 100`), no trailing comments, imperative-mood comments, one argument per line
  for long signatures, random seeds default to 1.
- Commits: code changes go to this repo; data changes (seeds, ratings, digests, library) go
  to the data repo. Never commit data here.
