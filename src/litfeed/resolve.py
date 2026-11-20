"""Turn pasted paper identifiers (links, IDs, DOIs, titles) into Semantic Scholar papers.

Recognized forms, one per line:
    https://www.semanticscholar.org/paper/<title-slug>/<40-hex id>, or a bare 40-hex id
    https://arxiv.org/abs/2401.12345v2, arxiv.org/pdf/..., arXiv:2401.12345, or 2401.12345
    https://doi.org/10.18653/v1/2023.acl-long.1, or a bare 10.xxxx/... DOI
    https://aclanthology.org/2023.acl-long.1(.pdf)
    CorpusId:12345
Anything else is treated as a title and matched with S2's title-match search.
"""

import re
import urllib.error

from litfeed.s2 import S2Client

S2_ID_PATTERN = re.compile(r"(?:^|/)([0-9a-f]{40})(?:[/?#]|$)")
ARXIV_PATTERN = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*|^)(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})"
    r"(?:v\d+)?(?:\.pdf)?/?$",
    re.IGNORECASE,
)
DOI_PATTERN = re.compile(r"(?:doi\.org/|doi:\s*|^)(10\.\d{4,9}/\S+)$", re.IGNORECASE)
ACL_PATTERN = re.compile(r"aclanthology\.org/([A-Za-z0-9.-]+?)(?:\.pdf)?/?$")
CORPUS_PATTERN = re.compile(r"^corpusid:\s*(\d+)$", re.IGNORECASE)


def lookup_key(text: str) -> str | None:
    """Return the S2 lookup ID for an identifier, or None if it looks like a title.

    Args:
        text: One pasted line.

    Returns:
        A paper ID S2 accepts (`<hex>`, `ARXIV:...`, `DOI:...`, `ACL:...`, `CorpusId:...`).
    """
    text = text.strip()
    if match := S2_ID_PATTERN.search(text):
        return match.group(1)
    if match := CORPUS_PATTERN.match(text):
        return f"CorpusId:{match.group(1)}"
    if match := ACL_PATTERN.search(text):
        return f"ACL:{match.group(1)}"
    if match := ARXIV_PATTERN.search(text):
        return f"ARXIV:{match.group(1)}"
    if match := DOI_PATTERN.search(text):
        return f"DOI:{match.group(1).rstrip('.')}"
    return None


def resolve_lines(
    lines: list[str],
    client: S2Client,
    fields: str,
) -> list[dict]:
    """Resolve pasted lines to S2 papers.

    Args:
        lines: Pasted identifiers or titles (blank lines are skipped).
        client: S2 client.
        fields: S2 paper fields to fetch.

    Returns:
        One dict per non-blank line: `input`, `paper` (S2 dict or None), and `how`
        ("id", "title match", or an error message).
    """
    inputs = [line.strip() for line in lines if line.strip()]
    keys = {text: lookup_key(text) for text in inputs}
    id_keys = sorted({key for key in keys.values() if key})
    papers_by_key = {}
    if id_keys:
        for key, paper in zip(id_keys, client.paper_batch(id_keys, fields, keep_missing=True)):
            papers_by_key[key] = paper

    results = []
    for text in inputs:
        key = keys[text]
        if key:
            paper = papers_by_key.get(key)
            how = "id" if paper else f"not found on S2 ({key})"
        else:
            paper = title_match(text, client, fields)
            how = "title match" if paper else "no title match"
        results.append({"input": text, "paper": paper, "how": how})
    return results


def title_match(
    title: str,
    client: S2Client,
    fields: str,
) -> dict | None:
    """Return S2's best title match, or None (S2 answers 404 when nothing matches)."""
    try:
        payload = client.get("/paper/search/match", {"query": title, "fields": fields})
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    matches = payload.get("data") or []
    return matches[0] if matches else None


PAPER_FIELDS = (
    "title,abstract,year,publicationDate,venue,authors,externalIds,citationCount,"
    "isOpenAccess,openAccessPdf"
)


def paper_record(paper: dict) -> dict:
    """Flatten an S2 paper (fetched with `PAPER_FIELDS`) into the record shape the rest of the
    package uses (author names as strings)."""
    return {
        "paperId": paper["paperId"],
        "title": paper.get("title"),
        "abstract": paper.get("abstract"),
        "year": paper.get("year"),
        "publicationDate": paper.get("publicationDate"),
        "venue": paper.get("venue"),
        "authors": [author.get("name") for author in paper.get("authors") or []],
        "externalIds": paper.get("externalIds") or {},
        "citationCount": paper.get("citationCount"),
        "openAccessPdf": paper.get("openAccessPdf"),
    }
