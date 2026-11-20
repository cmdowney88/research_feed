---
name: deep-dive
description: Run a deep-dive literature search for a research project from a written description — query planning, Semantic Scholar relevance and full-text snippet search, relevance scoring against the project, a citation-graph hop, user-confirmed seeds, all-years recommendations, reading notes, and a synthesis. Invoke when the user asks for a deep dive, literature review, or "what's out there" for a project or idea that has no existing feed.
---

# Deep dive

Pipeline script: `scripts/deep_dive.py` (stages `search`, `recommend`, `notes`, `synthesize`).
Everything for a project lives in `projects/<slug>/` in the data directory (`$LITFEED_DATA`,
else `data/`; see `litfeed.paths`). Use the `literature` conda env:
`$CONDA_ENVS/literature/bin/python`.

The user can also run the whole pipeline from the UI (`/deepdive/new`, then the project page's
seed checkpoint), with no session involved. That path skips this skill's description
distillation and search-gap review, so if the user brings a UI-started project here, offer
those: read `description.md` and `proposed_seeds.tsv` (or `seeds.tsv`) and comment.

**Keep paper text out of this session.** Every bulk read (scoring hundreds of abstracts,
reading full papers) happens inside the script's headless `claude -p --bare` calls. In this
session, read only the small outputs: `proposed_seeds.tsv`, the stage summaries, `synthesis.md`,
and individual notes the user asks about. Don't `cat` `candidates.jsonl`; query it with a short
Python one-liner when you need counts or a specific paper.

## Steps

1. **Description.** Ask for a written project description if the user hasn't given one: the
   setting, the questions, the kinds of literature to look for, and what is out of scope. Write
   it to `projects/<slug>/description.md` (short kebab-case slug), distilling rather than
   transcribing, and show the user the file so they can correct it. It drives every later stage.
2. **Search** (run in the background; ~5-10 min, ~$1-2):
   `python scripts/deep_dive.py search <slug>`. This plans queries (`queries.json`; delete it to
   re-plan), searches, scores, does one citation-graph hop, and writes `proposed_seeds.tsv`.
3. **Checkpoint: the user confirms the seeds.** Summarize `proposed_seeds.tsv` (the ranked
   `core` papers) compactly, grouped by `aspect`, and flag anything that looks off-target or any
   aspect of the description with no core papers (a search gap: suggest extra queries). The
   user prunes or adds; write the result to `projects/<slug>/seeds.tsv` (same columns). Never
   skip this step: the recommendation stage multiplies whatever the seeds are.
4. **Recommend** (background): `python scripts/deep_dive.py recommend <slug>`.
5. **Notes** (background; ~$0.05-0.20 per paper; add `--paper-ids ID ...` for papers the user singled out, since recommendations can push them below the cutoff): `python scripts/deep_dive.py notes <slug>
   --top 15`.
6. **Synthesize**: `python scripts/deep_dive.py synthesize <slug>` → `synthesis.md` and
   `reading_list.md`. Read `synthesis.md` and present its key points. Point out claims of the
   form "no prior work does X" as the ones to verify by hand: they rest on what one search found.
7. **Offer follow-ups:**
   - Promote the seeds to a standing weekly feed: copy `seeds.tsv` to `seeds/<feed>.tsv`
     (columns paperId, year, source, title), add the feed (with a description adapted from the
     project's) to `configs/feeds.yaml`, and write `feed: <feed>` to `projects/<slug>/project.yaml`
     so the project page's 👍/👎 edit that feed's seeds.
   - Point the user to the project page: `python scripts/serve_ui.py` → `/project/<slug>`.
   - Save key papers to the library (`litfeed.library.save_paper`, collection = the slug or an
     existing feed).
8. Commit the project directory (`description.md`, `queries.json`, `candidates.jsonl`, seeds,
   notes, `synthesis.md`, `reading_list.md`).

## Notes

- Relevance labels: core > related > background > irrelevant, judged against the description
  only (not the taste profile).
- S2 lookups are cached (`cache/s2/`), so re-running a stage after editing seeds or the
  description mostly costs only the LLM calls. Papers keep their label once scored; to
  re-score after a big description change, delete `candidates.jsonl`.
- The search draws from all years; the weekly feeds only see roughly the last two months.
