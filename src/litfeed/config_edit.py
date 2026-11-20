"""Comment-preserving edits to `configs/feeds.yaml` (used by the web UI).

`litfeed.feeds.load_config` stays the reader; this module only writes. It round-trips the file
with ruamel.yaml, which keeps comments, quoting, and indentation, so hand edits survive.
"""

import io
import re
import textwrap
import threading
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml.tokens import CommentToken

from litfeed.feeds import CONFIG_PATH

FEED_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_FEED_NAMES = {"citing_me", "flagged_authors", "candidates", "excluded", "general"}
DESCRIPTION_WIDTH = 92

# serialize config writes (the UI server handles requests on several threads)
_CONFIG_LOCK = threading.Lock()


def _yaml() -> YAML:
    """A round-trip YAML instance matching the file's existing layout."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _load(config_path: Path):
    return _yaml().load(config_path.read_text())


def _dump(data, config_path: Path) -> None:
    buffer = io.StringIO()
    _yaml().dump(data, buffer)
    config_path.write_text(buffer.getvalue())


def add_flagged_author(
    name: str,
    author_ids: list[str],
    config_path: Path = CONFIG_PATH,
) -> list[str]:
    """Add an author (or more S2 IDs for an existing one) to `flagged_authors`.

    Args:
        name: Display name; an existing entry with this name gains the new IDs.
        author_ids: S2 author IDs (S2 often splits one person across several).
        config_path: The feeds config (override in tests).

    Returns:
        The author's full ID list after the edit.

    Raises:
        ValueError: If the name is empty or an ID is not numeric.
    """
    name = " ".join(name.split())
    if not name:
        raise ValueError("empty author name")
    if not author_ids or not all(str(author_id).isdigit() for author_id in author_ids):
        raise ValueError("author IDs must be numeric S2 IDs")
    with _CONFIG_LOCK:
        data = _load(config_path)
        flagged = data.get("flagged_authors")
        if flagged is None:
            data["flagged_authors"] = {}
            flagged = data["flagged_authors"]
        existing = [str(author_id) for author_id in flagged.get(name) or []]
        new_ids = []
        for author_id in map(str, author_ids):
            if author_id not in existing and author_id not in new_ids:
                new_ids.append(author_id)
        if name in flagged:
            # extend in place to keep the entry's flow/block style
            flagged[name].extend(DoubleQuotedScalarString(i) for i in new_ids)
        else:
            flagged[name] = _yaml().load(flow_list(new_ids))
        _dump(data, config_path)
    return existing + new_ids


def flow_list(values: list[str]) -> str:
    """Render IDs as a quoted YAML flow sequence, e.g. ["1", "2"]."""
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def add_feed(
    name: str,
    description: str,
    priority: str = "high",
    config_path: Path = CONFIG_PATH,
    replace: str | None = None,
) -> None:
    """Append a feed definition under `feeds:`, or put it in place of the feed `replace`
    (used to swap out the template's placeholder feed).

    Args:
        name: Feed key (lowercase letters, digits, underscores); also the seed file stem.
        description: What triage reads to judge relevance; wrapped as a folded block.
        priority: "high" or "low".
        config_path: The feeds config (override in tests).
        replace: Name of a feed to remove and take the place of, if present.

    Raises:
        ValueError: On a malformed, reserved, or existing name, empty description, or bad
            priority.
    """
    if not FEED_NAME_PATTERN.match(name) or name in RESERVED_FEED_NAMES:
        raise ValueError(f"bad feed name: {name!r} (use lowercase letters, digits, underscores)")
    description = " ".join(description.split())
    if not description:
        raise ValueError("a feed needs a description (triage reads it)")
    if priority not in ("high", "low"):
        raise ValueError("priority must be high or low")
    wrapped = textwrap.fill(description, width=DESCRIPTION_WIDTH)
    snippet = (
        f"priority: {priority}\n"
        "description: >-\n" + textwrap.indent(wrapped, "  ") + "\n"
    )
    with _CONFIG_LOCK:
        data = _load(config_path)
        if name in data["feeds"]:
            raise ValueError(f"feed {name!r} already exists")
        feeds = data["feeds"]
        new_feed = _yaml().load(snippet)
        if replace is not None and replace in feeds:
            # take the placeholder's place, and its trailing comments if it was last
            position = list(feeds).index(replace)
            placeholder = feeds[replace]
            feeds.insert(position, name, new_feed)
            if isinstance(placeholder, CommentedMap):
                _move_trailing_comment(placeholder, feeds[name])
            del feeds[replace]
        else:
            previous_last = feeds[list(feeds)[-1]] if feeds else None
            feeds[name] = new_feed
            if isinstance(previous_last, CommentedMap):
                _move_trailing_comment(previous_last, feeds[name])
        _dump(data, config_path)


def _move_trailing_comment(source: CommentedMap, target: CommentedMap) -> None:
    """Move the comment block after `source`'s last value to after `target`'s last value.

    ruamel attaches comments that follow a mapping (here: commented-out feeds and the next
    section's header) to the mapping's last value, so a feed appended after it would land
    below them. Leave a blank line in its place.
    """
    last_key = list(source)[-1]
    comments = source.ca.items.get(last_key)
    if not comments or comments[2] is None:
        source.ca.items[last_key] = [None, None, CommentToken("\n", CommentMark(0)), None]
        return
    target.ca.items[list(target)[-1]] = [None, None, comments[2], None]
    comments[2] = CommentToken("\n", CommentMark(0))


def set_author_id(
    author_id: str,
    config_path: Path = CONFIG_PATH,
) -> None:
    """Set the user's own S2 author ID (`author_id`), adding the key if it is missing.

    Raises:
        ValueError: If the ID is not numeric.
    """
    author_id = str(author_id).strip()
    if not author_id.isdigit():
        raise ValueError("author IDs are numeric S2 IDs")
    with _CONFIG_LOCK:
        data = _load(config_path)
        if "author_id" in data:
            data["author_id"] = DoubleQuotedScalarString(author_id)
        else:
            data.insert(0, "author_id", DoubleQuotedScalarString(author_id))
        _dump(data, config_path)
