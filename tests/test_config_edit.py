import shutil
from pathlib import Path

import pytest

from litfeed.config_edit import add_feed, add_flagged_author, set_author_id
from litfeed.feeds import load_config

FIXTURE_CONFIG = Path(__file__).resolve().parent / "fixtures/data/configs/feeds.yaml"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "feeds.yaml"
    shutil.copy(FIXTURE_CONFIG, path)
    return path


def test_add_flagged_author_new_and_merge(config_path: Path) -> None:
    assert add_flagged_author("New  Person", ["11", "22", "11"], config_path) == ["11", "22"]
    first = next(iter(load_config(config_path)["flagged_authors"]))
    existing = load_config(config_path)["flagged_authors"][first]
    merged = add_flagged_author(first, [existing[0], "33"], config_path)
    assert merged == existing + ["33"]
    flagged = load_config(config_path)["flagged_authors"]
    assert flagged["New Person"] == ["11", "22"]
    assert flagged[first] == existing + ["33"]


def test_add_flagged_author_rejects_bad_ids(config_path: Path) -> None:
    with pytest.raises(ValueError):
        add_flagged_author("Someone", ["abc"], config_path)
    with pytest.raises(ValueError):
        add_flagged_author(" ", ["1"], config_path)


def test_add_feed_keeps_comments_and_order(config_path: Path) -> None:
    before = config_path.read_text()
    add_feed("brand_new", "Papers about something. " * 10, "low", config_path)
    after = config_path.read_text()
    # every original line survives, comments included
    assert all(line in after.splitlines() for line in before.splitlines())
    config = load_config(config_path)
    assert list(config["feeds"])[-1] == "brand_new"
    assert config["feeds"]["brand_new"]["priority"] == "low"
    assert config["feeds"]["brand_new"]["description"].startswith("Papers about something.")
    # the new feed sits inside the feeds block, above the next section's comments
    assert after.index("brand_new:") < after.index("# a commented-out feed")
    assert after.index("brand_new:") < after.index("flagged_authors:")
    assert after.index("brand_new:") < after.index("# Papers by these authors")


@pytest.mark.parametrize(
    "name, description, priority",
    [
        ("Bad-Name", "x", "high"),
        ("citing_me", "x", "high"),
        ("ok_name", "  ", "high"),
        ("ok_name", "x", "urgent"),
    ],
)
def test_add_feed_rejects(config_path: Path, name: str, description: str, priority: str) -> None:
    with pytest.raises(ValueError):
        add_feed(name, description, priority, config_path)


def test_add_feed_rejects_existing(config_path: Path) -> None:
    existing = next(iter(load_config(config_path)["feeds"]))
    with pytest.raises(ValueError):
        add_feed(existing, "x", "high", config_path)


def test_set_author_id(config_path: Path) -> None:
    set_author_id("12345", config_path)
    assert load_config(config_path)["author_id"] == "12345"
    assert 'author_id: "12345"' in config_path.read_text()
    with pytest.raises(ValueError):
        set_author_id("abc", config_path)


def test_add_feed_replaces_placeholder(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    shutil.copy(Path(__file__).resolve().parents[1] / "examples" / "feeds.yaml", path)
    add_feed("real_feed", "Real papers.", "high", path, replace="example_feed")
    config = load_config(path)
    assert list(config["feeds"]) == ["real_feed"]
    text = path.read_text()
    # the comments after the placeholder now follow the new feed, above the next section
    assert text.index("real_feed:") < text.index("# Papers by these authors")
