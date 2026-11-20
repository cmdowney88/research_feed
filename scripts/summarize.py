"""Write reading notes for the top-tier papers of a triage file.

For each paper at or above `--max-tier` (default: tier 1 only) that has no note yet, get its
full text (arXiv LaTeX source first, then open-access PDF via `pdftotext`, else the abstract),
send it to headless Claude with `prompts/summarize.md` + `taste/profile.md`, and write
`notes/<paperId>.md`. Papers are processed in parallel; each runs in its own `claude -p --bare`
call with no tools, so the paper text never reaches an interactive session.

Example:
    python scripts/summarize.py triage/2026-11-10.jsonl
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from litfeed.notes import write_note
from litfeed.paths import DATA_ROOT, PROMPTS_DIR

NOTES_DIR = DATA_ROOT / "notes"
PROMPT_PATH = PROMPTS_DIR / "summarize.md"
PROFILE_PATH = DATA_ROOT / "taste" / "profile.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("triage_path", type=Path)
    parser.add_argument("--max-tier", type=int, default=1)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true", help="rewrite existing notes")
    parser.add_argument(
        "--max-papers",
        type=int,
        default=None,
        help="cap on notes written this run (a cost guard for unattended runs)",
    )
    args = parser.parse_args()

    records = [json.loads(line) for line in args.triage_path.open()]
    todo = [
        record
        for record in records
        if record["tier"] <= args.max_tier
        and (args.overwrite or not (NOTES_DIR / f"{record['paperId']}.md").exists())
    ]
    if args.max_papers is not None and len(todo) > args.max_papers:
        print(
            f"WARNING: {len(todo)} papers qualify; summarizing the first {args.max_papers}",
            file=sys.stderr,
        )
        todo = todo[: args.max_papers]
    print(f"{len(todo)} papers to summarize", file=sys.stderr)

    system_prompt = PROMPT_PATH.read_text().replace("{profile}", PROFILE_PATH.read_text())
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for status in executor.map(
            lambda record: write_note(record, system_prompt, NOTES_DIR, args.model),
            todo,
        ):
            print(status, file=sys.stderr)


if __name__ == "__main__":
    main()
