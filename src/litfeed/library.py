"""Save papers to a reference library: one running .bib file per collection, plus PDFs.

Saving is deliberately separate from rating: a saved paper is a reference to keep (e.g. a
background citation), not a signal to fetch more papers like it, so it never becomes a seed.

Layout:
    library/<collection>.bib   BibTeX entries (git-tracked)
    library/index.tsv          paperId, key, collection, saved_at, pdf, bib_source
    library/pdfs/<key>.pdf     downloaded PDFs (gitignored)

BibTeX sources, best first: ACL Anthology, DOI content negotiation (skipping arXiv's own
DOIs), arXiv, Semantic Scholar's generated entry, then a minimal @misc entry built from the
paper's metadata (`bib_source` in the index records which one was used).
"""

import csv
import datetime
import re
import sys
import threading
import urllib.request
from pathlib import Path

from litfeed.paths import DATA_ROOT
from litfeed.s2 import S2Client

LIBRARY_DIR = DATA_ROOT / "library"
INDEX_PATH = LIBRARY_DIR / "index.tsv"
PDF_DIR = LIBRARY_DIR / "pdfs"
INDEX_FIELDS = ["paperId", "key", "collection", "saved_at", "pdf", "bib_source"]
GENERAL_COLLECTION = "general"
USER_AGENT = "litfeed/0.1 (personal literature tool)"
ENTRY_KEY_PATTERN = re.compile(r"^\s*@\w+\s*\{\s*([^,\s]+)\s*,")

# serialize index/.bib writes (the UI server handles requests on several threads)
_WRITE_LOCK = threading.RLock()


def _library_dir() -> Path:
    return INDEX_PATH.parent


def _get(url: str, accept: str | None = None) -> bytes | None:
    """GET a URL, returning None on any network or HTTP error."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except OSError as error:
        print(f"GET {url} failed: {error}", file=sys.stderr)
        return None


def _valid_bibtex(payload: bytes | None) -> str | None:
    """Return the decoded entry if it looks like a single BibTeX entry, else None."""
    if not payload:
        return None
    text = payload.decode(errors="replace").strip()
    return text if ENTRY_KEY_PATTERN.match(text) else None


def one_field_per_line(entry: str) -> str:
    """Reformat a single-line entry (as DOI content negotiation returns) to one field per line."""
    if "\n" in entry.strip():
        return entry
    expanded = re.sub(r",\s*(\w+)\s*=\s*", lambda match: f",\n  {match.group(1)} = ", entry)
    return re.sub(r"\}\s*$", "\n}", expanded.strip())


def fetch_bibtex(record: dict) -> tuple[str, str] | None:
    """Return (bibtex, source) for a paper, trying sources from best to worst."""
    external_ids = record.get("externalIds") or {}
    acl_id = external_ids.get("ACL")
    if acl_id:
        entry = _valid_bibtex(_get(f"https://aclanthology.org/{acl_id}.bib"))
        if entry:
            return entry, "acl"
    doi = external_ids.get("DOI")
    if doi and not doi.lower().startswith("10.48550/"):
        entry = _valid_bibtex(_get(f"https://doi.org/{doi}", accept="application/x-bibtex"))
        if entry:
            return one_field_per_line(entry), "doi"
    arxiv_id = external_ids.get("ArXiv")
    if arxiv_id:
        entry = _valid_bibtex(_get(f"https://arxiv.org/bibtex/{arxiv_id}"))
        if entry:
            return entry, "arxiv"
    try:
        paper = S2Client(max_retries=2).get(
            f"/paper/{record['paperId']}",
            {"fields": "citationStyles"},
        )
        entry = (paper.get("citationStyles") or {}).get("bibtex")
    except OSError:
        entry = None
    if entry and ENTRY_KEY_PATTERN.match(entry):
        return entry.strip(), "s2"
    return generated_bibtex(record)


def generated_bibtex(record: dict) -> tuple[str, str] | None:
    """Build a minimal @misc entry from the record's own metadata (last resort)."""
    title = record.get("title")
    authors = record.get("authors") or []
    if not title or not authors:
        return None
    year = str(record.get("year") or "")
    first_surname = re.sub(r"[^a-z]", "", authors[0].split()[-1].lower()) or "anon"
    first_word = re.sub(r"[^a-z]", "", title.split()[0].lower())
    key = f"{first_surname}{year}{first_word}"
    fields = [f"  title = {{{title}}}", f"  author = {{{' and '.join(authors)}}}"]
    if year:
        fields.append(f"  year = {{{year}}}")
    if record.get("venue"):
        fields.append(f"  howpublished = {{{record['venue']}}}")
    fields.append(f"  url = {{https://www.semanticscholar.org/paper/{record['paperId']}}}")
    return "@misc{" + key + ",\n" + ",\n".join(fields) + "\n}", "generated"


def entry_key(entry: str) -> str:
    """Return the citation key of a BibTeX entry."""
    match = ENTRY_KEY_PATTERN.match(entry)
    if match is None:
        raise ValueError("not a BibTeX entry")
    return match.group(1)


def with_key(entry: str, new_key: str) -> str:
    """Return `entry` with its citation key replaced by `new_key`."""
    return ENTRY_KEY_PATTERN.sub(lambda match: match.group(0).replace(match.group(1), new_key),
                                 entry, count=1)


def remove_entry(bib_text: str, key: str) -> str:
    """Remove the entry with citation `key` from a .bib file's text (brace-matched)."""
    match = re.search(r"@\w+\s*\{\s*" + re.escape(key) + r"\s*,", bib_text)
    if match is None:
        return bib_text
    depth = 0
    end = match.end()
    for position in range(bib_text.index("{", match.start()), len(bib_text)):
        if bib_text[position] == "{":
            depth += 1
        elif bib_text[position] == "}":
            depth -= 1
            if depth == 0:
                end = position + 1
                break
    return (bib_text[: match.start()] + bib_text[end:].lstrip("\n")).rstrip() + "\n"


def load_index(index_path: Path | None = None) -> dict[str, dict]:
    """Return library index rows keyed by paper ID."""
    index_path = index_path or INDEX_PATH
    if not index_path.exists():
        return {}
    with index_path.open(newline="") as handle:
        return {row["paperId"]: row for row in csv.DictReader(handle, delimiter="\t")}


def _write_index(rows: dict[str, dict], index_path: Path | None = None) -> None:
    index_path = index_path or INDEX_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows.values():
            writer.writerow(row)


def default_collection(record: dict, collections: list[str]) -> str:
    """Pick the seed feed where the paper ranked best, else the general collection."""
    ranked = [
        (rank, feed)
        for feed, rank in (record.get("feeds") or {}).items()
        if feed in collections and rank
    ]
    return min(ranked)[1] if ranked else GENERAL_COLLECTION


def download_pdf(record: dict, key: str) -> str:
    """Download the paper's PDF to `library/pdfs/<key>.pdf`; return its path or ""."""
    urls = []
    arxiv_id = (record.get("externalIds") or {}).get("ArXiv")
    if arxiv_id:
        urls.append(f"https://arxiv.org/pdf/{arxiv_id}")
    open_access_url = (record.get("openAccessPdf") or {}).get("url")
    if open_access_url:
        urls.append(open_access_url)
    for url in urls:
        payload = _get(url)
        # only keep real PDFs, not landing pages
        if payload and payload.startswith(b"%PDF"):
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path = PDF_DIR / f"{key}.pdf"
            pdf_path.write_bytes(payload)
            return str(pdf_path.relative_to(DATA_ROOT))
    return ""


def save_paper(record: dict, collection: str) -> dict:
    """Thread-safe wrapper around `_save_paper`; see it for details."""
    with _WRITE_LOCK:
        return _save_paper(record, collection)


def _save_paper(record: dict, collection: str) -> dict:
    """Add a paper's BibTeX to `library/<collection>.bib` and download its PDF.

    Saving an already-saved paper to a different collection moves it.

    Returns:
        The paper's index row.

    Raises:
        LookupError: If no BibTeX entry could be found from any source.
    """
    index = load_index()
    existing = index.get(record["paperId"])
    if existing and existing["collection"] == collection:
        return existing
    if existing:
        _unsave_paper(record["paperId"])
        index = load_index()

    found = fetch_bibtex(record)
    if found is None:
        raise LookupError(f"no BibTeX found for {record['paperId']}")
    entry, source = found

    # make the key unique across the whole library
    taken = {row["key"] for row in index.values()}
    key = entry_key(entry)
    base_key = key
    suffix = ord("b")
    while key in taken:
        key = f"{base_key}{chr(suffix)}"
        suffix += 1
    entry = with_key(entry, key)

    bib_path = _library_dir() / f"{collection}.bib"
    bib_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = bib_path.read_text() if bib_path.exists() else ""
    separator = "\n" if existing_text and not existing_text.endswith("\n\n") else ""
    bib_path.write_text(existing_text + separator + entry + "\n")

    row = {
        "paperId": record["paperId"],
        "key": key,
        "collection": collection,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pdf": existing["pdf"] if existing and existing["pdf"] else download_pdf(record, key),
        "bib_source": source,
    }
    index[record["paperId"]] = row
    _write_index(index)
    return row


def unsave_paper(paper_id: str) -> None:
    """Remove a paper's entry from its .bib file and the index (the PDF is kept)."""
    with _WRITE_LOCK:
        _unsave_paper(paper_id)


def _unsave_paper(paper_id: str) -> None:
    index = load_index()
    row = index.pop(paper_id, None)
    if row is None:
        return
    bib_path = _library_dir() / f"{row['collection']}.bib"
    if bib_path.exists():
        bib_path.write_text(remove_entry(bib_path.read_text(), row["key"]))
    _write_index(index)
