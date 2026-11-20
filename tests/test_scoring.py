import pytest

from litfeed.scoring import author_role_weight, citation_strength, recency_weight


def make_paper(author_ids: list[str]) -> dict:
    return {"authors": [{"authorId": author_id, "name": ""} for author_id in author_ids]}


def test_citation_strength_plain() -> None:
    assert citation_strength({"isInfluential": False, "contexts": []}) == 1.0


def test_citation_strength_influential_with_contexts() -> None:
    reference = {"isInfluential": True, "contexts": ["a", "b"]}
    assert citation_strength(reference) == pytest.approx(2.5)


def test_citation_strength_caps_contexts() -> None:
    reference = {"isInfluential": False, "contexts": ["x"] * 10}
    assert citation_strength(reference) == pytest.approx(2.0)


def test_citation_strength_handles_null_contexts() -> None:
    assert citation_strength({"contexts": None}) == 1.0


@pytest.mark.parametrize(
    ("author_ids", "expected"),
    [
        (["me", "b", "c"], 1.0),
        (["a", "b", "me"], 1.0),
        (["a", "me", "c"], 0.5),
        (["me"], 1.0),
    ],
)
def test_author_role_weight(author_ids: list[str], expected: float) -> None:
    assert author_role_weight(make_paper(author_ids), "me", 0.5) == expected


def test_recency_weight_halves_per_half_life() -> None:
    assert recency_weight(2026, 2026, 3.0) == 1.0
    assert recency_weight(2023, 2026, 3.0) == pytest.approx(0.5)
    assert recency_weight(None, 2026, 3.0) == 1.0
