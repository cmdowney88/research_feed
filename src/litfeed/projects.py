"""Deep-dive projects: candidates, the accompanying feed, and thumbs-up/down ratings.

A project lives in `projects/<slug>/`. Its optional `project.yaml` links it to a feed:

    feed: asr_documentation

Thumbs are stored append-only in `projects/<slug>/thumbs.jsonl` (latest per paper wins) and
edit the linked feed's seeds:

- up: add the paper to `seeds/<feed>.tsv` if it isn't there.
- down: remove the paper from `seeds/<feed>.tsv` if it is there.
- neutral (None): no seed change of its own.

Each thumb records the seed change it made, and setting a new thumb first undoes the previous
one's change. So "up, then neutral" removes the seed that "up" added (but never a seed that was
already there), and "down, then neutral" restores the seed that "down" removed.
"""

import datetime
import json
import re
import threading
from pathlib import Path

import yaml

from litfeed.feeds import add_seed, read_seed_rows, remove_seed
from litfeed.paths import DATA_ROOT

PROJECTS_DIR = DATA_ROOT / "projects"
SLUG_PATTERN = re.compile(r"^[0-9a-z][0-9a-z_-]*$")
THUMB_VALUES = ("up", "down", None)

# serialize thumb writes (the UI server handles requests on several threads)
_THUMB_LOCK = threading.Lock()


def project_dir(slug: str, projects_dir: Path | None = None) -> Path | None:
    """Return the directory of an existing project, or None for unknown or malformed slugs."""
    if not SLUG_PATTERN.match(slug):
        return None
    directory = (projects_dir or PROJECTS_DIR) / slug
    return directory if (directory / "description.md").exists() else None


def list_projects(projects_dir: Path | None = None) -> list[str]:
    """Return the slugs of all projects."""
    root = projects_dir or PROJECTS_DIR
    if not root.exists():
        return []
    return sorted(path.parent.name for path in root.glob("*/description.md"))


def load_project_config(directory: Path) -> dict:
    """Parse `project.yaml` ({} if absent)."""
    config_path = directory / "project.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def load_candidates(directory: Path) -> dict[str, dict]:
    """Return the project's scored candidates keyed by paper ID."""
    candidates_path = directory / "candidates.jsonl"
    if not candidates_path.exists():
        return {}
    with candidates_path.open() as handle:
        return {record["paperId"]: record for record in map(json.loads, handle)}


def load_thumbs(directory: Path) -> dict[str, dict]:
    """Return the latest thumb entry per paper ID."""
    thumbs_path = directory / "thumbs.jsonl"
    latest = {}
    if thumbs_path.exists():
        for line in thumbs_path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                latest[entry["paperId"]] = entry
    return latest


def _undo_seed_change(
    feed: str,
    change: dict | None,
    seeds_dir: Path | None,
) -> None:
    """Reverse a previously recorded seed change."""
    if not change:
        return
    if change["action"] == "added":
        remove_seed(feed, change["row"]["paperId"], seeds_dir)
    elif change["action"] == "removed":
        add_seed(feed, change["row"], seeds_dir)


def set_thumb(
    directory: Path,
    record: dict,
    thumb: str | None,
    seeds_dir: Path | None = None,
) -> dict:
    """Record a thumb for `record` and apply its effect on the linked feed's seeds.

    Args:
        directory: The project directory.
        record: The candidate record (needs `paperId`, `title`, `year`).
        thumb: "up", "down", or None (neutral).
        seeds_dir: Override for the seeds directory (tests).

    Returns:
        The stored thumb entry, including `seed_change` and `in_seeds`.

    Raises:
        ValueError: If `thumb` is not one of `THUMB_VALUES`.
    """
    if thumb not in THUMB_VALUES:
        raise ValueError(f"bad thumb: {thumb!r}")
    feed = load_project_config(directory).get("feed")
    paper_id = record["paperId"]
    with _THUMB_LOCK:
        previous = load_thumbs(directory).get(paper_id) or {}
        seed_change = None
        if feed:
            _undo_seed_change(feed, previous.get("seed_change"), seeds_dir)
            if thumb == "up":
                row = {
                    "paperId": paper_id,
                    "year": record.get("year") or "",
                    "source": f"thumbs:{directory.name}",
                    "title": record.get("title") or "",
                }
                if add_seed(feed, row, seeds_dir):
                    seed_change = {"action": "added", "row": row}
            elif thumb == "down":
                removed = remove_seed(feed, paper_id, seeds_dir)
                if removed is not None:
                    seed_change = {"action": "removed", "row": removed}
        in_seeds = bool(feed) and any(
            row["paperId"] == paper_id for row in read_seed_rows(feed, seeds_dir)
        )
        entry = {
            "paperId": paper_id,
            "title": record.get("title"),
            "thumb": thumb,
            "feed": feed,
            "seed_change": seed_change,
            "in_seeds": in_seeds,
            "at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with (directory / "thumbs.jsonl").open("a") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
