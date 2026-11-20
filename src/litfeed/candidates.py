"""Clean up fetched candidates before triage: merge duplicate versions, tag flagged authors."""

import re


def normalize_title(title: str) -> str:
    """Lowercase and strip non-alphanumerics so preprint and venue versions compare equal."""
    return re.sub(r"[^a-z0-9]", "", title.lower())


def merge_duplicates(records: list[dict]) -> list[dict]:
    """Merge records with the same normalized title into one, unioning their feeds.

    The kept record is the first one with an abstract (else the first seen); the IDs of the
    other versions are kept in `duplicateIds` so they can be marked seen too.
    """
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(normalize_title(record.get("title") or record["paperId"]), []).append(
            record
        )

    merged = []
    for group in groups.values():
        with_abstract = [record for record in group if record.get("abstract")]
        kept = dict(with_abstract[0] if with_abstract else group[0])
        kept["feeds"] = {}
        kept["duplicateIds"] = []
        for record in group:
            kept["feeds"].update(record["feeds"])
            if record["paperId"] != kept["paperId"]:
                kept["duplicateIds"].append(record["paperId"])
        merged.append(kept)
    return merged


def tag_flagged_authors(
    records: list[dict],
    flagged_authors: dict[str, list[str]],
) -> None:
    """Set `flaggedAuthors` on each record to the flagged names among its author IDs."""
    id_to_name = {
        author_id: name for name, author_ids in flagged_authors.items() for author_id in author_ids
    }
    for record in records:
        names = set()
        for author_id in record.get("authorIds") or []:
            if author_id in id_to_name:
                names.add(id_to_name[author_id])
        record["flaggedAuthors"] = sorted(names)
