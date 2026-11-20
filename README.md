# research_feed

Personal research-literature feeds built on the public
[Semantic Scholar API](https://api.semanticscholar.org/api-docs/), with LLM triage against your
own research taste. Instead of an S2 account's feeds, each feed is a curated list of seed
papers; every week the system:

1. fetches recommendations for each feed (plus papers citing your work and new papers by
   authors you flag),
2. triages them into four tiers with a headless `claude -p` call, using your written taste
   profile and your past corrections,
3. writes reading notes for tier-1 papers from their full text (arXiv LaTeX source, else the
   open-access PDF), and
4. renders a digest you rate in a local web UI. Your ratings feed back into the next fetch
   (as positive/negative seeds) and the next triage (as calibration examples).

The UI also saves papers to per-feed BibTeX files (with PDFs), edits feeds and their seeds,
flags authors, and runs **deep dives**: from a written project description to searched,
scored, and recommended literature, reading notes, and a synthesis.

> **Platform support.** The pipeline scripts and the web UI run anywhere Python and the
> `claude` CLI run, but the **automated weekly run is macOS-only for now**: scheduling uses
> launchd, `scripts/weekly.sh` uses macOS notifications, and the setup page's one-click run
> and schedule buttons are only offered on macOS. On Linux or Windows, run the four pipeline
> steps by hand or from your own scheduler (see [Weekly run](#weekly-run)).

## Setup

```bash
conda env create -f environment.yml
conda activate literature
python scripts/serve_ui.py
```

The first start creates your data directory and opens a **setup checklist** at
`http://127.0.0.1:8765/setup`, which walks you through:

1. **API keys and tools.** An Anthropic API key (required: triage, notes, and deep dives call
   Claude Code headlessly, `claude -p --bare`, which bills `ANTHROPIC_API_KEY`) and, optionally,
   a free [S2 API key](https://www.semanticscholar.org/product/api#api-key), which makes fetches
   much faster. Both can be tested in place; they are saved to the data directory's `.env`.
   It also checks for the `claude` CLI and (optional) `pdftotext`.
2. **You on Semantic Scholar** (optional): pick your S2 author profile, so papers citing your
   work are surfaced and the next steps can start from your publications.
3. **Your research taste:** a profile in prose that triage reads. It can be drafted from your
   publications plus a few notes of yours (one Claude call, a few cents), then edited.
4. **Your first feeds:** rank the papers your own work cites and tick them into feeds, paste
   papers by link/DOI/title, or start from a deep dive.
5. **Authors to follow** (optional), the **weekly schedule** (macOS only), and a **first run**
   (macOS only) so you have a digest to rate right away.

Everything the checklist does can also be done by hand; the files are described below.

### Code and data are separate

This repository is only the framework. Everything personal (feed definitions, seeds, taste
profile, ratings, digests, notes, deep-dive projects, the library, caches, and your `.env`)
lives in a **data directory**: `$LITFEED_DATA` if set, else `data/` in this checkout (which
is gitignored, so you can make it its own private git repository). The UI creates it on first
start (or run `python scripts/init_data.py`) from `examples/`:

```
data/
  .env                API keys (S2_API_KEY, ANTHROPIC_API_KEY) and LITFEED_PYTHON
  configs/feeds.yaml  feeds, your S2 author ID, flagged authors
  taste/profile.md    your research taste, in prose (read by triage and the note writer)
  taste/ratings.jsonl your ratings from the UI
  seeds/<feed>.tsv    seed papers per feed (paperId, year, source, title)
  triage/, digests/, notes/, projects/, library/, state/
```

## Weekly run

Any platform, by hand (or from cron, Task Scheduler, etc.):

```bash
python scripts/fetch_recommendations.py                # -> fetches/<date>.jsonl
python scripts/triage.py data/fetches/<date>.jsonl     # -> triage/<date>.jsonl
python scripts/summarize.py data/triage/<date>.jsonl   # -> notes/<id>.md for tier 1
python scripts/render_digest.py data/triage/<date>.jsonl  # -> digests/<date>.md, marks seen
python scripts/serve_ui.py                             # rate at http://127.0.0.1:8765
```

**macOS only, for now:** `scripts/weekly.sh` runs the first four steps and posts a macOS
notification at the end, and the setup page (or `scripts/install_weekly.sh`) schedules it with
launchd (Wednesdays 11:00 by default). launchd doesn't read your shell profile, so the job
takes `S2_API_KEY`, `ANTHROPIC_API_KEY`, and `LITFEED_PYTHON` from the data directory's `.env`
(the setup page fills these in). Porting the scheduler to cron or systemd timers would be a
welcome contribution.

Rough costs with Sonnet: triage ~$1 per few hundred papers; notes ~$0.10–0.20 each; a deep
dive ~$5.

## Local UI security

The UI binds to 127.0.0.1 only, accepts requests only with a localhost `Host` header, and
accepts API calls only as same-origin JSON, so other websites open in your browser can't
drive it. It has no login: anyone with a shell on your machine can use it.

## Deep dives

In the UI, **New deep dive** takes a project description, searches S2 (relevance and full-text
snippet search, planned by Claude), scores every candidate against the description, follows
one hop of the citation graph, and stops for you to confirm seed papers. It then pulls
all-years recommendations, writes notes for the top papers, and writes a synthesis with
linked citations. The project page's 👍/👎 edit a linked feed's seeds. The same pipeline runs
from the command line: `python scripts/deep_dive.py {search,recommend,notes,synthesize} <slug>`.

## Tests

```bash
pytest
bash tests/js/run_ui_smoke.sh && bash tests/js/run_manage_smoke.sh   # macOS (JXA), no browser
```

Tests use the fixture data in `tests/fixtures/data`, never your data directory.

## License

MIT; see [LICENSE](LICENSE).
