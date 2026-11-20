"""Load feed definitions, seed lists, and seen-paper state."""

import csv
import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from litfeed.paths import DATA_ROOT

CONFIG_PATH = DATA_ROOT / "configs" / "feeds.yaml"
SEEDS_DIR = DATA_ROOT / "seeds"
SEEN_PATH = DATA_ROOT / "state" / "seen.tsv"


@dataclass
class Feed:
    """One seed-based feed.

    Attributes:
        name: Feed key in `configs/feeds.yaml`; seeds live in `seeds/<name>.tsv`.
        priority: "high" or "low".
        description: Prose used by triage to judge relevance.
        positive_ids: S2 paper IDs of positive seeds.
        negative_ids: S2 paper IDs from `seeds/<name>.negative.tsv`, if present.
    """

    name: str
    priority: str
    description: str
    positive_ids: list[str] = field(default_factory=list)
    negative_ids: list[str] = field(default_factory=list)


def read_paper_ids(path: Path) -> list[str]:
    """Read the `paperId` column of a seed TSV; return [] if the file does not exist."""
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [row["paperId"] for row in csv.DictReader(handle, delimiter="\t")]


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Parse `configs/feeds.yaml`."""
    return yaml.safe_load(config_path.read_text())


def load_feeds(
    config: dict,
    seeds_dir: Path = SEEDS_DIR,
) -> list[Feed]:
    """Build a `Feed` for each entry under `feeds:` in the config, with its seeds loaded."""
    feeds = []
    for name, spec in config["feeds"].items():
        feeds.append(
            Feed(
                name=name,
                priority=spec["priority"],
                description=spec["description"],
                positive_ids=read_paper_ids(seeds_dir / f"{name}.tsv"),
                negative_ids=read_paper_ids(seeds_dir / f"{name}.negative.tsv"),
            )
        )
    return feeds


def load_seen_ids(seen_path: Path = SEEN_PATH) -> set[str]:
    """Return IDs of papers already shown in a digest."""
    return set(read_paper_ids(seen_path))


SEED_FIELDS = ["paperId", "year", "source", "title"]

# serialize seed-file edits (the UI server handles requests on several threads); reentrant so
# add/remove can call write
_SEEDS_LOCK = threading.RLock()


def seed_row(paper: dict, source: str) -> dict:
    """Build a seed row from an S2 paper or candidate record."""
    return {
        "paperId": paper["paperId"],
        "year": paper.get("year") or "",
        "source": source,
        "title": paper.get("title") or "",
    }


def read_seed_rows(feed_name: str, seeds_dir: Path | None = None) -> list[dict]:
    """Return the rows of `seeds/<feed_name>.tsv` ([] if it does not exist)."""
    path = (seeds_dir or SEEDS_DIR) / f"{feed_name}.tsv"
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_seed_rows(
    feed_name: str,
    rows: list[dict],
    seeds_dir: Path | None = None,
) -> None:
    """Overwrite `seeds/<feed_name>.tsv` with `rows` (columns `SEED_FIELDS`)."""
    path = (seeds_dir or SEEDS_DIR) / f"{feed_name}.tsv"
    with _SEEDS_LOCK, path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SEED_FIELDS,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def add_seed(
    feed_name: str,
    row: dict,
    seeds_dir: Path | None = None,
) -> bool:
    """Append `row` to a feed's seeds unless its paper is already there; return whether added."""
    with _SEEDS_LOCK:
        rows = read_seed_rows(feed_name, seeds_dir)
        if any(existing["paperId"] == row["paperId"] for existing in rows):
            return False
        write_seed_rows(feed_name, rows + [row], seeds_dir)
        return True


def remove_seed(
    feed_name: str,
    paper_id: str,
    seeds_dir: Path | None = None,
) -> dict | None:
    """Remove a paper from a feed's seeds; return the removed row, or None if absent."""
    with _SEEDS_LOCK:
        rows = read_seed_rows(feed_name, seeds_dir)
        removed = next((row for row in rows if row["paperId"] == paper_id), None)
        if removed is not None:
            write_seed_rows(
                feed_name,
                [row for row in rows if row["paperId"] != paper_id],
                seeds_dir,
            )
        return removed
