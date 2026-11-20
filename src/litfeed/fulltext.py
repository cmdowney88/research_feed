"""Get a paper's full text cheaply: arXiv LaTeX source first, then open-access PDF text.

Downloads are untrusted: each paper's archive is extracted into its own directory with
tarfile's "data" filter (no absolute paths, links outside the tree, or special files), and
nothing in it is executed. Only `.tex` files are read; `pdftotext` is the only external tool.
"""

import gzip
import io
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from litfeed.paths import DATA_ROOT

FULLTEXT_CACHE = DATA_ROOT / "cache" / "fulltext"
USER_AGENT = "litfeed/0.1 (personal literature tool)"


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _strip_latex_comments(text: str) -> str:
    """Remove `%` comments (but not escaped `\\%`) and collapse runs of blank lines."""
    without_comments = re.sub(r"(?<!\\)%.*", "", text)
    return re.sub(r"\n\s*\n+", "\n\n", without_comments)


def _latex_text(extract_dir: Path) -> str | None:
    """Concatenate the .tex files, main file (the one with \\documentclass) first."""
    tex_files = sorted(extract_dir.rglob("*.tex"))
    if not tex_files:
        return None
    contents = {path: path.read_text(errors="replace") for path in tex_files}
    main_files = [path for path, text in contents.items() if "\\documentclass" in text]
    ordered = main_files + [path for path in tex_files if path not in main_files]
    parts = [f"% FILE: {path.name}\n{_strip_latex_comments(contents[path])}" for path in ordered]
    return "\n\n".join(parts)


def arxiv_latex(arxiv_id: str) -> str | None:
    """Return the LaTeX source of an arXiv paper as text, or None if unavailable."""
    extract_dir = FULLTEXT_CACHE / "arxiv" / arxiv_id.replace("/", "_")
    if not extract_dir.exists():
        try:
            payload = _download(f"https://arxiv.org/e-print/{arxiv_id}")
        except OSError as error:
            print(f"arXiv e-print failed for {arxiv_id}: {error}", file=sys.stderr)
            return None
        # be polite to arXiv between downloads
        time.sleep(3)
        extract_dir.mkdir(parents=True)
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
                archive.extractall(extract_dir, filter="data")
        except tarfile.TarError:
            # a single gzipped .tex file, or a PDF-only submission
            try:
                text = gzip.decompress(payload).decode(errors="replace")
            except OSError:
                text = ""
            if "\\documentclass" in text or "\\begin{document}" in text:
                (extract_dir / "main.tex").write_text(text)
    return _latex_text(extract_dir)


def pdf_text(url: str, cache_name: str) -> str | None:
    """Download a PDF and convert it to text with `pdftotext -layout`."""
    if shutil.which("pdftotext") is None:
        return None
    pdf_dir = FULLTEXT_CACHE / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{cache_name}.pdf"
    text_path = pdf_dir / f"{cache_name}.txt"
    if not text_path.exists():
        try:
            pdf_path.write_bytes(_download(url))
        except OSError as error:
            print(f"PDF download failed for {url}: {error}", file=sys.stderr)
            return None
        completed = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), str(text_path)],
            capture_output=True,
        )
        if completed.returncode != 0:
            return None
    return text_path.read_text(errors="replace")


def get_fulltext(record: dict) -> tuple[str | None, str]:
    """Return (text, source) for a paper record, where source is "latex", "pdf", or "none"."""
    arxiv_id = (record.get("externalIds") or {}).get("ArXiv")
    if arxiv_id:
        text = arxiv_latex(arxiv_id)
        if text:
            return text, "latex"
        text = pdf_text(f"https://arxiv.org/pdf/{arxiv_id}", arxiv_id.replace("/", "_"))
        if text:
            return text, "pdf"
    pdf_url = (record.get("openAccessPdf") or {}).get("url")
    if pdf_url:
        text = pdf_text(pdf_url, record["paperId"])
        if text:
            return text, "pdf"
    return None, "none"
