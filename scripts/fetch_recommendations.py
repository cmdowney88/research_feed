"""Fetch this week's candidate papers for every feed.

For each seed-based feed, query the S2 Recommendations API with the feed's positive and
negative seeds. Separately, collect papers citing the author's own work and recent papers by
flagged authors (`flagged_authors` in `configs/feeds.yaml`). Papers the user rated tier 1 or 4
are added to the feeds that surfaced them as extra positive or negative seeds. Merge everything into
one record per paper (tagged with every feed that surfaced it and its rank there), drop papers
that are seeds, excluded, or already shown in a digest, and write the result as JSON lines.

This script does not update `state/seen.tsv`; that happens when a digest is written, so a test
fetch never hides papers from a later digest.

Example:
    python scripts/fetch_recommendations.py --limit 100
"""

import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

from litfeed.feeds import SEEDS_DIR, load_config, load_feeds, load_seen_ids, read_paper_ids
from litfeed.ratings import feedback_seeds, load_ratings
from litfeed.paths import DATA_ROOT
from litfeed.s2 import S2Client

PAPER_FIELDS = (
    "title,abstract,year,publicationDate,venue,authors,externalIds,citationCount,"
    "isOpenAccess,openAccessPdf"
)


def add_candidate(
    candidates: dict[str, dict],
    paper: dict,
    feed_name: str,
    rank: int,
) -> None:
    """Merge `paper` into `candidates`, recording which feed surfaced it and at what rank."""
    paper_id = paper["paperId"]
    if paper_id not in candidates:
        record = {key: paper.get(key) for key in PAPER_FIELDS.split(",")}
        record["paperId"] = paper_id
        record["authors"] = [author["name"] for author in paper.get("authors") or []]
        record["authorIds"] = [author.get("authorId") for author in paper.get("authors") or []]
        record["feeds"] = {}
        candidates[paper_id] = record
    candidates[paper_id]["feeds"][feed_name] = rank


def is_recent(
    paper: dict,
    cutoff_date: str,
) -> bool:
    """Return whether `paper` was published on or after `cutoff_date` (ISO format).

    Papers without a publication date count as recent if their year is the cutoff's year or
    later.
    """
    publication_date = paper.get("publicationDate")
    if publication_date:
        return publication_date >= cutoff_date
    year = paper.get("year")
    return year is not None and year >= int(cutoff_date[:4])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=100, help="recommendations per feed")
    parser.add_argument(
        "--author-window-days",
        type=int,
        default=60,
        help="how far back to look for flagged authors' papers",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_ROOT / "fetches" / f"{datetime.date.today().isoformat()}.jsonl",
    )
    args = parser.parse_args()

    config = load_config()
    feeds = load_feeds(config)
    client = S2Client()

    # collect every paper that should never be recommended back to the user
    known_ids = set(load_seen_ids())
    for seed_file in SEEDS_DIR.glob("*.tsv"):
        if seed_file.name not in ("candidates.tsv", "citing_me.tsv"):
            known_ids.update(read_paper_ids(seed_file))

    # add seeds learned from ratings: user tier 1 -> positive, user tier 4 -> negative
    learned = feedback_seeds(load_ratings(), [feed.name for feed in feeds])

    candidates: dict[str, dict] = {}
    for feed in feeds:
        positive_ids = list(dict.fromkeys(feed.positive_ids + learned[feed.name]["positive"]))
        negative_ids = list(dict.fromkeys(feed.negative_ids + learned[feed.name]["negative"]))
        print(
            f"{feed.name}: {len(positive_ids)} positive seeds "
            f"({len(learned[feed.name]['positive'])} from ratings), "
            f"{len(negative_ids)} negative ({len(learned[feed.name]['negative'])} from ratings)",
            file=sys.stderr,
        )
        if not positive_ids:
            print(f"{feed.name}: no seeds yet; skipped", file=sys.stderr)
            continue
        papers = client.recommend(
            positive_ids,
            negative_ids,
            fields=PAPER_FIELDS,
            limit=args.limit,
        )
        for rank, paper in enumerate(papers, start=1):
            add_candidate(candidates, paper, feed.name, rank)

    # papers citing the user's own work (skipped when no author_id is configured)
    if config.get("author_id"):
        own_papers = client.get_all(
            f"/author/{config['author_id']}/papers",
            fields="title",
            use_cache=False,
        )
        excluded_own = set(config.get("excluded_own_papers") or [])
        own_ids = {paper["paperId"] for paper in own_papers} - excluded_own
        for own_id in sorted(own_ids):
            citations = client.get_all(
                f"/paper/{own_id}/citations",
                fields=PAPER_FIELDS,
                page_size=1000,
                use_cache=False,
            )
            for citation in citations:
                citing = citation.get("citingPaper") or {}
                if citing.get("paperId"):
                    add_candidate(candidates, citing, "citing_me", rank=0)

    # fetch recent papers by flagged authors directly, so they surface even if no feed does
    cutoff = (datetime.date.today() - datetime.timedelta(days=args.author_window_days)).isoformat()
    for author_name, author_ids in (config.get("flagged_authors") or {}).items():
        for author_id in author_ids:
            author_papers = client.get_all(
                f"/author/{author_id}/papers",
                fields=PAPER_FIELDS,
                use_cache=False,
            )
            for paper in author_papers:
                if is_recent(paper, cutoff):
                    add_candidate(candidates, paper, "flagged_authors", rank=0)

    fresh = [
        record
        for paper_id, record in candidates.items()
        if paper_id not in known_ids and paper_id not in own_ids
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as handle:
        for record in fresh:
            handle.write(json.dumps(record) + "\n")

    feed_counts = Counter(name for record in fresh for name in record["feeds"])
    print(f"{len(fresh)} new candidates ({len(candidates)} before filtering) -> {args.output}")
    for name, count in feed_counts.most_common():
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
