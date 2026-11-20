"""Scoring helpers for ranking an author's references as recommendation seeds."""


def citation_strength(reference: dict) -> float:
    """Score one citation edge from S2's influence flag and its number of citation contexts.

    Args:
        reference: One item from the S2 `/paper/{id}/references` endpoint.

    Returns:
        1, plus 1 if the citation is marked influential, plus 0.25 per context (max 4).
    """
    strength = 1.0
    if reference.get("isInfluential"):
        strength += 1.0
    strength += 0.25 * min(len(reference.get("contexts") or []), 4)
    return strength


def author_role_weight(
    paper: dict,
    author_id: str,
    middle_author_weight: float,
) -> float:
    """Weight a paper by the author's position in its author list.

    Args:
        paper: An S2 paper record with an `authors` list of `{authorId, name}` dicts.
        author_id: The S2 author ID whose taste is being modeled.
        middle_author_weight: Weight applied when the author is neither first nor last.

    Returns:
        1.0 for first or last author, otherwise `middle_author_weight`.
    """
    author_ids = [author["authorId"] for author in paper["authors"]]
    if author_ids and author_id in (author_ids[0], author_ids[-1]):
        return 1.0
    return middle_author_weight


def recency_weight(
    paper_year: int | None,
    newest_year: int,
    half_life: float,
) -> float:
    """Halve a paper's weight every `half_life` years before `newest_year`.

    A missing year is treated as `newest_year` (full weight).
    """
    if paper_year is None:
        paper_year = newest_year
    return 0.5 ** ((newest_year - paper_year) / half_life)
