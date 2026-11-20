from pathlib import Path

from litfeed.candidates import merge_duplicates, tag_flagged_authors
from litfeed.ratings import append_rating, calibration_examples, feedback_seeds, load_ratings


def make_record(paper_id: str, tier: int, feeds: list[str], title: str = "T") -> dict:
    return {"paperId": paper_id, "title": title, "tier": tier, "feeds": {f: 1 for f in feeds}}


def test_latest_rating_wins(tmp_path: Path) -> None:
    ratings_path = tmp_path / "ratings.jsonl"
    record = make_record("p1", 2, ["asr"])
    append_rating(record, 1, "", "d", ratings_path=ratings_path)
    append_rating(record, 4, "changed my mind", "d", ratings_path=ratings_path)
    ratings = load_ratings(ratings_path)
    assert ratings["p1"]["user_tier"] == 4
    assert ratings["p1"]["predicted_tier"] == 2


def test_feedback_seeds_route_by_feed_and_tier(tmp_path: Path) -> None:
    ratings_path = tmp_path / "ratings.jsonl"
    append_rating(make_record("good", 3, ["asr", "citing_me"]), 1, "", "d", ratings_path)
    append_rating(make_record("bad", 2, ["adaptation"]), 4, "", "d", ratings_path)
    append_rating(make_record("meh", 2, ["asr"]), 2, "", "d", ratings_path)
    append_rating(make_record("orphan", 3, ["citing_me"]), 1, "", "d", ratings_path)
    seeds = feedback_seeds(load_ratings(ratings_path), ["asr", "adaptation"])
    assert seeds["asr"] == {"positive": ["good"], "negative": []}
    assert seeds["adaptation"] == {"positive": [], "negative": ["bad"]}


def test_calibration_examples_only_informative(tmp_path: Path) -> None:
    ratings_path = tmp_path / "ratings.jsonl"
    append_rating(make_record("agree", 2, ["asr"], "Agreed"), 2, "", "d", ratings_path)
    append_rating(make_record("fix", 4, ["asr"], "Corrected"), 1, "", "d", ratings_path)
    append_rating(make_record("noted", 3, ["asr"], "Noted"), None, "ok as is", "d", ratings_path)
    text = calibration_examples(load_ratings(ratings_path))
    assert "Agreed" not in text
    assert "Corrected" in text and "researcher says tier 1" in text
    assert "Noted" in text and "ok as is" in text


def test_merge_duplicates_unions_feeds_and_prefers_abstract() -> None:
    records = [
        {"paperId": "a", "title": "Double Trouble!", "abstract": None, "feeds": {"x": 1}},
        {"paperId": "b", "title": "double trouble", "abstract": "text", "feeds": {"y": 2}},
        {"paperId": "c", "title": "Other", "abstract": None, "feeds": {"x": 3}},
    ]
    merged = merge_duplicates(records)
    assert len(merged) == 2
    kept = next(record for record in merged if record["paperId"] == "b")
    assert kept["feeds"] == {"x": 1, "y": 2}
    assert kept["duplicateIds"] == ["a"]


def test_tag_flagged_authors() -> None:
    records = [{"authorIds": ["1", "2"]}, {"authorIds": [None, "9"]}]
    tag_flagged_authors(records, {"Ada": ["2", "3"]})
    assert records[0]["flaggedAuthors"] == ["Ada"]
    assert records[1]["flaggedAuthors"] == []
