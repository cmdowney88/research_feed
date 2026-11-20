"""Write reading notes for single papers from their full text, via headless Claude.

Used by the weekly pipeline (`scripts/summarize.py`, framed by the taste profile) and by deep
dives (`scripts/deep_dive.py`, framed by a project description). The caller supplies the
system prompt, so the framing lives entirely in the prompt template.
"""

import datetime
import json
from pathlib import Path

from litfeed.fulltext import get_fulltext
from litfeed.llm import run_claude

MAX_TEXT_CHARS = 150_000

NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "method": {"type": "string"},
        "relevance": {"type": "string"},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tldr", "findings", "method", "relevance", "caveats"],
}


def build_user_message(record: dict, text: str | None, source: str) -> str:
    """Combine paper metadata with its full text (or abstract) for the note writer."""
    metadata = {
        "title": record.get("title"),
        "authors": record.get("authors"),
        "venue": record.get("venue"),
        "date": record.get("publicationDate") or record.get("year"),
        "text_source": source,
    }
    if text is None:
        body = f"ABSTRACT ONLY:\n{record.get('abstract') or '(no abstract available)'}"
    elif len(text) > MAX_TEXT_CHARS:
        body = text[:MAX_TEXT_CHARS] + "\n\n[... truncated ...]"
    else:
        body = text
    return f"Paper metadata:\n{json.dumps(metadata, ensure_ascii=False)}\n\nPaper text:\n{body}"


def render_note(
    record: dict,
    summary: dict,
    source: str,
    model: str,
    relevance_heading: str = "How it bears on your work",
) -> str:
    """Format a summary as a Markdown note with YAML front matter."""
    arxiv_id = (record.get("externalIds") or {}).get("ArXiv") or ""
    front_matter = [
        "---",
        f"paperId: {record['paperId']}",
        f"title: {json.dumps(record.get('title'), ensure_ascii=False)}",
        f"arxiv: {json.dumps(arxiv_id)}",
        f"tier: {record.get('tier')}",
        f"feeds: {json.dumps(sorted(record.get('feeds') or {}))}",
        f"text_source: {source}",
        f"model: {model}",
        f"written: {datetime.date.today().isoformat()}",
        "---",
    ]
    sections = [
        f"# {record.get('title')}",
        "",
        "## TL;DR",
        summary["tldr"],
        "",
        "## Findings",
        *[f"- {finding}" for finding in summary["findings"]],
        "",
        "## Method",
        summary["method"],
        "",
        f"## {relevance_heading}",
        summary["relevance"],
    ]
    if summary["caveats"]:
        sections += ["", "## Caveats", *[f"- {caveat}" for caveat in summary["caveats"]]]
    return "\n".join(front_matter + sections) + "\n"


def write_note(
    record: dict,
    system_prompt: str,
    notes_dir: Path,
    model: str = "sonnet",
    relevance_heading: str = "How it bears on your work",
) -> str:
    """Fetch full text, call headless Claude, write `<notes_dir>/<paperId>.md`.

    Returns:
        A one-line status for logging.
    """
    text, source = get_fulltext(record)
    result = run_claude(
        system_prompt,
        build_user_message(record, text, source),
        NOTE_SCHEMA,
        model=model,
    )
    title = (record.get("title") or "")[:60]
    if result.output is None:
        return f"FAILED {title}: {result.error[:300]}"
    notes_dir.mkdir(parents=True, exist_ok=True)
    note_path = notes_dir / f"{record['paperId']}.md"
    note_path.write_text(render_note(record, result.output, source, model, relevance_heading))
    return f"ok [{source}] ${result.cost_usd:.3f} {title}"
