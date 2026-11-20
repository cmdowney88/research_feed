"""Render a triage file into a read-only Markdown digest and record its papers as seen.

The Markdown digest is a git-readable archive; reading notes are linked, not inlined. Rate
papers in the local UI (`scripts/serve_ui.py`), which writes `taste/ratings.jsonl`.

Example:
    python scripts/render_digest.py triage/2026-11-10.jsonl
"""

import argparse
import csv
import datetime
import json
from pathlib import Path

from litfeed.feeds import SEEN_PATH
from litfeed.paths import DATA_ROOT

TIER_HEADINGS = {
    1: "Tier 1: read carefully",
    2: "Tier 2: skim",
    3: "Tier 3: worth knowing it exists",
    4: "Tier 4: probably not interesting",
}
FEED_LABELS = {
    "multilingual_adaptation": "adaptation",
    "multilingual_asr": "ASR",
    "unsupervised_segmentation": "segmentation",
    "citing_me": "cites you",
    "flagged_authors": "flagged author",
}


def format_authors(authors: list[str], flagged: list[str]) -> str:
    """Show up to four authors, bolding flagged ones, plus "et al." when truncated."""
    shown = []
    for name in authors[:4]:
        shown.append(f"**{name}**" if any(flag.split()[-1] in name for flag in flagged) else name)
    if len(authors) > 4:
        hidden_flagged = [
            flag for flag in flagged if not any(flag.split()[-1] in name for name in authors[:4])
        ]
        shown.append("et al." + "".join(f", **{flag}**" for flag in hidden_flagged))
    return ", ".join(shown)


def format_entry(record: dict) -> str:
    """Render one paper as a Markdown block with links, metadata, rationale, and feedback."""
    paper_id = record["paperId"]
    links = [f"[S2](https://www.semanticscholar.org/paper/{paper_id})"]
    arxiv_id = (record.get("externalIds") or {}).get("ArXiv")
    if arxiv_id:
        links.append(f"[arXiv](https://arxiv.org/abs/{arxiv_id})")

    metadata = [format_authors(record.get("authors") or [], record.get("flaggedAuthors") or [])]
    if record.get("venue"):
        metadata.append(record["venue"])
    metadata.append(str(record.get("publicationDate") or record.get("year") or "n.d."))
    feeds = [FEED_LABELS.get(feed, feed) for feed in sorted(record["feeds"])]
    metadata.append("feeds: " + ", ".join(feeds))

    return "\n".join(
        [
            f"### {record['title']}",
            f"<!-- {paper_id} -->",
            " · ".join(metadata) + " · " + " ".join(links),
            "",
            f"{record['why']}",
            "",
        ]
        + ([f"Reading note: [notes/{paper_id}.md](../notes/{paper_id}.md)", ""]
           if (DATA_ROOT / "notes" / f"{paper_id}.md").exists() else [])
    )


def sort_key(record: dict) -> tuple:
    """Order within a tier: flagged authors, then citing-me, then newest first."""
    date = str(record.get("publicationDate") or record.get("year") or "")
    return (
        not record.get("flaggedAuthors"),
        "citing_me" not in record["feeds"],
        "".join(chr(255 - ord(character)) for character in date),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("triage_path", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--no-mark-seen",
        action="store_true",
        help="do not add these papers to state/seen.tsv",
    )
    args = parser.parse_args()
    output_path = args.output or DATA_ROOT / "digests" / args.triage_path.with_suffix(".md").name

    records = [json.loads(line) for line in args.triage_path.open()]
    today = datetime.date.today().isoformat()
    counts = {tier: sum(1 for record in records if record["tier"] == tier) for tier in range(1, 5)}

    lines = [
        f"# Literature digest: {today}",
        "",
        f"{len(records)} papers: "
        + ", ".join(f"{counts[tier]} in tier {tier}" for tier in range(1, 5))
        + f". Triage model: {records[0]['model'] if records else 'n/a'}.",
        "",
        "Read-only archive. Rate papers in the local UI: `python scripts/serve_ui.py`.",
        "",
    ]
    for tier in range(1, 5):
        tier_records = sorted((r for r in records if r["tier"] == tier), key=sort_key)
        if not tier_records:
            continue
        lines += [f"## {TIER_HEADINGS[tier]} ({len(tier_records)})", ""]
        lines += [format_entry(record) for record in tier_records]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    print(f"digest -> {output_path}")

    if args.no_mark_seen:
        return
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not SEEN_PATH.exists()
    with SEEN_PATH.open("a", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        if is_new_file:
            writer.writerow(["paperId", "first_shown", "tier", "title"])
        for record in records:
            for paper_id in [record["paperId"], *(record.get("duplicateIds") or [])]:
                writer.writerow([paper_id, today, record["tier"], record["title"]])
    print(f"marked {len(records)} papers seen in {SEEN_PATH}")


if __name__ == "__main__":
    main()
