"""User ratings: storage, and how they feed back into fetching and triage.

`taste/ratings.jsonl` is append-only; the latest line for a paper wins. Each line holds
`paperId`, `title`, `feeds`, `predicted_tier`, `user_tier` (1-4, or null when only a note was
given), `note`, `digest`, and `rated_at`.
"""

import datetime
import json
from pathlib import Path

from litfeed.paths import DATA_ROOT

RATINGS_PATH = DATA_ROOT / "taste" / "ratings.jsonl"


def load_ratings(ratings_path: Path = RATINGS_PATH) -> dict[str, dict]:
    """Return the latest rating per paper ID."""
    latest = {}
    if not ratings_path.exists():
        return latest
    for line in ratings_path.read_text().splitlines():
        if line.strip():
            rating = json.loads(line)
            latest[rating["paperId"]] = rating
    return latest


def append_rating(
    record: dict,
    user_tier: int | None,
    note: str,
    digest: str,
    ratings_path: Path = RATINGS_PATH,
) -> dict:
    """Append a rating for triage `record` and return it."""
    rating = {
        "paperId": record["paperId"],
        "title": record.get("title"),
        "feeds": sorted(record.get("feeds") or {}),
        "predicted_tier": record.get("tier"),
        "user_tier": user_tier,
        "note": note,
        "digest": digest,
        "rated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    ratings_path.parent.mkdir(parents=True, exist_ok=True)
    with ratings_path.open("a") as handle:
        handle.write(json.dumps(rating, ensure_ascii=False) + "\n")
    return rating


def feedback_seeds(
    ratings: dict[str, dict],
    feed_names: list[str],
    max_per_feed: int = 50,
) -> dict[str, dict[str, list[str]]]:
    """Derive extra seeds per feed from ratings.

    A paper the user rated tier 1 becomes a positive seed, and one rated tier 4 a negative
    seed, for every seed-based feed that surfaced it. Papers surfaced only by `citing_me` or
    `flagged_authors` are not attached to any feed. The most recent `max_per_feed` of each
    kind are kept.

    Returns:
        {feed_name: {"positive": [...], "negative": [...]}}
    """
    seeds = {name: {"positive": [], "negative": []} for name in feed_names}
    ordered = sorted(ratings.values(), key=lambda rating: rating["rated_at"], reverse=True)
    for rating in ordered:
        kind = {1: "positive", 4: "negative"}.get(rating.get("user_tier"))
        if kind is None:
            continue
        for feed in rating["feeds"]:
            if feed in seeds and len(seeds[feed][kind]) < max_per_feed:
                seeds[feed][kind].append(rating["paperId"])
    return seeds


def calibration_examples(
    ratings: dict[str, dict],
    max_examples: int = 40,
) -> str:
    """Format informative past ratings (corrections or notes) as text for the triage prompt."""
    informative = [
        rating
        for rating in ratings.values()
        if rating.get("note")
        or (rating.get("user_tier") and rating["user_tier"] != rating.get("predicted_tier"))
    ]
    informative.sort(key=lambda rating: rating["rated_at"], reverse=True)
    lines = []
    for rating in informative[:max_examples]:
        user_tier = rating.get("user_tier") or rating.get("predicted_tier")
        sources = [
            label
            for feed, label in (
                ("citing_me", "cites the researcher"),
                ("flagged_authors", "by a flagged author"),
            )
            if feed in rating.get("feeds", [])
        ]
        source_text = f" [{', '.join(sources)}]" if sources else ""
        line = f"- \"{rating['title']}\"{source_text}: predicted tier {rating['predicted_tier']}"
        line += f", researcher says tier {user_tier}"
        if rating.get("note"):
            line += f". Note: {rating['note']}"
        lines.append(line)
    return "\n".join(lines)
