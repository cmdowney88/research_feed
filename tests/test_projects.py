from pathlib import Path

import pytest

from litfeed.feeds import read_seed_rows, write_seed_rows
from litfeed.projects import load_thumbs, set_thumb


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "description.md").write_text("# Demo\n")
    (project / "project.yaml").write_text("feed: demo_feed\n")
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    write_seed_rows(
        "demo_feed",
        [{"paperId": "curated", "year": "2020", "source": "cited", "title": "Curated"}],
        seeds_dir,
    )
    return project, seeds_dir


def seed_ids(seeds_dir: Path) -> list[str]:
    return [row["paperId"] for row in read_seed_rows("demo_feed", seeds_dir)]


def record(paper_id: str) -> dict:
    return {"paperId": paper_id, "title": paper_id.title(), "year": 2024}


def test_up_adds_and_neutral_undoes(setup: tuple[Path, Path]) -> None:
    project, seeds_dir = setup
    entry = set_thumb(project, record("new"), "up", seeds_dir)
    assert entry["in_seeds"] and seed_ids(seeds_dir) == ["curated", "new"]
    set_thumb(project, record("new"), None, seeds_dir)
    assert seed_ids(seeds_dir) == ["curated"]


def test_up_on_existing_seed_then_neutral_keeps_it(setup: tuple[Path, Path]) -> None:
    project, seeds_dir = setup
    entry = set_thumb(project, record("curated"), "up", seeds_dir)
    assert entry["seed_change"] is None
    set_thumb(project, record("curated"), None, seeds_dir)
    assert seed_ids(seeds_dir) == ["curated"]


def test_down_removes_and_neutral_restores_row(setup: tuple[Path, Path]) -> None:
    project, seeds_dir = setup
    set_thumb(project, record("curated"), "down", seeds_dir)
    assert seed_ids(seeds_dir) == []
    set_thumb(project, record("curated"), None, seeds_dir)
    rows = read_seed_rows("demo_feed", seeds_dir)
    assert rows == [{"paperId": "curated", "year": "2020", "source": "cited", "title": "Curated"}]


def test_switching_up_to_down(setup: tuple[Path, Path]) -> None:
    project, seeds_dir = setup
    set_thumb(project, record("new"), "up", seeds_dir)
    entry = set_thumb(project, record("new"), "down", seeds_dir)
    assert seed_ids(seeds_dir) == ["curated"]
    assert entry["thumb"] == "down" and not entry["in_seeds"]
    assert load_thumbs(project)["new"]["thumb"] == "down"


def test_bad_thumb_rejected(setup: tuple[Path, Path]) -> None:
    project, seeds_dir = setup
    with pytest.raises(ValueError):
        set_thumb(project, record("x"), "sideways", seeds_dir)
