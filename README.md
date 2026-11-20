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

## Setup

```bash
conda env create -f environment.yml
conda activate literature
python scripts/init_data.py
```

Triage, notes, and deep dives call Claude Code
headlessly (`claude -p --bare`), which bills `ANTHROPIC_API_KEY`. A free
[S2 API key](https://www.semanticscholar.org/product/api#api-key) is optional but makes fetches
much faster.

### Code and data are separate

This repository is only the framework. Everything personal (feed definitions, seeds, taste
profile, ratings, digests, notes, deep-dive projects, the library, caches, and your `.env`)
lives in a **data directory**: `$LITFEED_DATA` if set, else `data/` in this checkout (which
is gitignored, so you can make it its own private git repository). `scripts/init_data.py`
creates it from `examples/`:

```
data/
  .env                API keys (S2_API_KEY, ANTHROPIC_API_KEY) and LITFEED_PYTHON
  configs/feeds.yaml  feeds, your S2 author ID, flagged authors
  taste/profile.md    your research taste, in prose (read by triage and the note writer)
  taste/ratings.jsonl your ratings from the UI
  seeds/<feed>.tsv    seed papers per feed (paperId, year, source, title)
  triage/, digests/, notes/, projects/, library/, state/
```

Then:

1. Write `taste/profile.md` (the template lists what helps) and describe your feeds in
   `configs/feeds.yaml`.
2. Add seeds: in the UI (`python scripts/serve_ui.py` → **Feeds & seeds**, paste arXiv/DOI/S2
   links or titles), from a deep dive, or bootstrapped from your own papers' references:
   `python scripts/seed_from_author.py --author-id <your S2 author ID>`, which ranks the papers
   you cite into `seeds/candidates.tsv` for you to sort into feeds.

## Weekly run

```bash
python scripts/fetch_recommendations.py                # -> fetches/<date>.jsonl
python scripts/triage.py data/fetches/<date>.jsonl     # -> triage/<date>.jsonl
python scripts/summarize.py data/triage/<date>.jsonl   # -> notes/<id>.md for tier 1
python scripts/render_digest.py data/triage/<date>.jsonl  # -> digests/<date>.md, marks seen
python scripts/serve_ui.py                             # rate at http://127.0.0.1:8765
```

`scripts/weekly.sh` runs the first four steps with a macOS notification at the end;
`scripts/install_weekly.sh` schedules it with launchd (Wednesdays 11:00 by default; edit
`configs/launchd/local.litfeed.weekly.plist`). Put `S2_API_KEY`, `ANTHROPIC_API_KEY`, and
`LITFEED_PYTHON` in the data directory's `.env`, since launchd doesn't read your shell profile.

Rough costs with Sonnet: triage ~$1 per few hundred papers; notes ~$0.10–0.20 each; a deep
dive ~$5.

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
