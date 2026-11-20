"""Assign tiers to a fetch's candidates with headless Claude, judged against the taste profile.

Steps: fill missing abstracts from arXiv, merge duplicate versions of the same paper, tag
flagged authors, then send batches of papers to `claude -p --bare` with `taste/profile.md`
(plus the user's past corrections and notes from `taste/ratings.jsonl` as calibration
examples) as the system prompt and a JSON schema for the output. `--bare` keeps the run
isolated from CLAUDE.md files, memory, and hooks, so tiers depend only on the profile, the
ratings, and the papers.
Authentication in bare mode is the ANTHROPIC_API_KEY, so this is billed to that key.

Writes `triage/<date>.jsonl`: one record per paper with the fetch metadata plus `tier`, `why`,
and `model`.

Example:
    python scripts/triage.py fetches/2026-11-10.jsonl --model sonnet
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from litfeed.arxiv import fetch_abstracts
from litfeed.candidates import merge_duplicates, tag_flagged_authors
from litfeed.feeds import load_config
from litfeed.llm import run_claude
from litfeed.ratings import calibration_examples, load_ratings
from litfeed.paths import DATA_ROOT, PROMPTS_DIR

PROMPT_PATH = PROMPTS_DIR / "triage.md"
PROFILE_PATH = DATA_ROOT / "taste" / "profile.md"
MAX_ABSTRACT_CHARS = 1500

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paperId": {"type": "string"},
                    "tier": {"type": "integer", "minimum": 1, "maximum": 4},
                    "why": {"type": "string"},
                },
                "required": ["paperId", "tier", "why"],
            },
        }
    },
    "required": ["items"],
}


def paper_for_prompt(record: dict) -> dict:
    """Reduce a candidate record to the fields the triage model needs."""
    abstract = record.get("abstract") or ""
    if len(abstract) > MAX_ABSTRACT_CHARS:
        abstract = abstract[:MAX_ABSTRACT_CHARS] + " [...]"
    return {
        "paperId": record["paperId"],
        "title": record.get("title"),
        "authors": (record.get("authors") or [])[:8],
        "venue": record.get("venue"),
        "date": record.get("publicationDate") or record.get("year"),
        "feeds": sorted(record["feeds"]),
        "flaggedAuthors": record.get("flaggedAuthors") or [],
        "abstract": abstract or None,
    }


def triage_batch(
    batch: list[dict],
    system_prompt: str,
    model: str,
) -> list[dict]:
    """Send one batch to headless Claude and return its list of {paperId, tier, why}."""
    user_message = "Triage these papers:\n\n" + json.dumps(
        [paper_for_prompt(record) for record in batch],
        ensure_ascii=False,
        indent=1,
    )
    result = run_claude(system_prompt, user_message, OUTPUT_SCHEMA, model=model)
    if result.output is None:
        print(f"claude failed: {result.error}", file=sys.stderr)
        return []
    print(f"  batch of {len(batch)} done (${result.cost_usd:.3f})", file=sys.stderr)
    return result.output.get("items", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("fetch_path", type=Path)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output_path = args.output or DATA_ROOT / "triage" / args.fetch_path.name

    config = load_config()
    records = [json.loads(line) for line in args.fetch_path.open()]

    # fill missing abstracts from arXiv
    missing = {}
    for record in records:
        arxiv_id = (record.get("externalIds") or {}).get("ArXiv")
        if not record.get("abstract") and arxiv_id:
            missing[arxiv_id] = record
    if missing:
        abstracts = fetch_abstracts(sorted(missing))
        for arxiv_id, abstract in abstracts.items():
            if arxiv_id in missing:
                missing[arxiv_id]["abstract"] = abstract
        print(f"filled {len(abstracts)}/{len(missing)} abstracts from arXiv", file=sys.stderr)

    records = merge_duplicates(records)
    tag_flagged_authors(records, config.get("flagged_authors") or {})
    no_abstract = sum(1 for record in records if not record.get("abstract"))
    print(f"{len(records)} papers after merging ({no_abstract} without abstract)", file=sys.stderr)

    system_prompt = PROMPT_PATH.read_text().replace("{profile}", PROFILE_PATH.read_text())
    examples = calibration_examples(load_ratings())
    if examples:
        system_prompt += (
            "\n\n# Calibration: the researcher's past corrections and notes\n\n"
            "Where these conflict with the profile, these are more recent and take precedence.\n\n"
            + examples
        )
    batches = [
        records[start : start + args.batch_size]
        for start in range(0, len(records), args.batch_size)
    ]
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = executor.map(
            lambda batch: triage_batch(batch, system_prompt, args.model),
            batches,
        )
        judgments = {item["paperId"]: item for batch_items in results for item in batch_items}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    missing_judgments = 0
    with output_path.open("w") as handle:
        for record in records:
            judgment = judgments.get(record["paperId"])
            if judgment is None:
                missing_judgments += 1
                continue
            record["tier"] = judgment["tier"]
            record["why"] = judgment["why"]
            record["model"] = args.model
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"{len(records) - missing_judgments} triaged -> {output_path}")
    if missing_judgments:
        print(f"WARNING: {missing_judgments} papers got no judgment; rerun", file=sys.stderr)


if __name__ == "__main__":
    main()
