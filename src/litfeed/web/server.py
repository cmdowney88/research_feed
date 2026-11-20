"""Local web UI for digests and deep-dive projects (standard library only, 127.0.0.1).

Pages:
    /                  index of digests and projects
    /digest/<date>     triage tiers, tier/note ratings → `taste/ratings.jsonl`, Save
    /project/<slug>    synthesis with clickable citations, papers by relevance, 👍/👎 →
                       `projects/<slug>/thumbs.jsonl` and the linked feed's seeds, Save; while
                       a deep dive runs, its progress and the seed checkpoint
    /feeds             seeds per feed (add, remove, save), flagged authors, new feeds
    /deepdive/new      start a deep dive from a written description
Paper API (POST, JSON; every request carries `digest`, `project`, or `seeds`):
    /api/rate          {paperId, user_tier, note}            digest only
    /api/thumb         {paperId, thumb: "up"|"down"|null}    project only
    /api/save          {paperId, collection|null}            any; null unsaves
Management API (POST, JSON): see `litfeed.web.manage.ROUTES`.

Page scripts and styles are files in `static/`; each page embeds its data as JSON.
"""

import html
import json
import re
import sys
import urllib.error
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from litfeed.feeds import load_config, read_seed_rows
from litfeed.library import GENERAL_COLLECTION, default_collection, load_index, save_paper
from litfeed.library import unsave_paper
from litfeed.projects import list_projects, load_candidates, load_project_config, load_thumbs
from litfeed.projects import project_dir, set_thumb
from litfeed.ratings import append_rating, load_ratings
from litfeed.paths import DATA_ROOT
from litfeed.web.manage import ROUTES, ApiError, feeds_page_body, feeds_page_data, fetch_record
from litfeed.web.manage import new_dive_body, project_pipeline_data

TRIAGE_DIR = DATA_ROOT / "triage"
NOTES_DIR = DATA_ROOT / "notes"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DIGEST_NAME_PATTERN = re.compile(r"^[0-9A-Za-z_-]+$")
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
REFERENCE_PATTERN = re.compile(r"^(\d+)\. .*semanticscholar\.org/paper/([0-9a-f]+)\s*$")
PROJECT_LABELS = ("core", "related", "background")


def read_note(notes_dir: Path, paper_id: str) -> str | None:
    """Return a note's Markdown body without its front matter and title, if it exists."""
    note_path = notes_dir / f"{paper_id}.md"
    if not note_path.exists():
        return None
    text = note_path.read_text()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return "\n".join(line for line in text.splitlines() if not line.startswith("# "))


def collections() -> list[str]:
    """Library collections: every feed, `general`, and every project."""
    return list(load_config()["feeds"]) + [GENERAL_COLLECTION] + list_projects()


def page(title: str, body: str, data: dict | None = None, script: str | None = None) -> bytes:
    """Wrap body HTML in a full page, embedding `data` as JSON for the page script."""
    data_tag = ""
    scripts = ""
    if data is not None:
        # escape "</" so paper text can't close the script tag
        payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        data_tag = f'<script type="application/json" id="data">{payload}</script>'
    if script:
        scripts = (
            '<script src="/static/common.js"></script>'
            f'<script src="/static/{script}"></script>'
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><link rel="stylesheet" href="/static/style.css"></head>
<body><main>{body}</main>{data_tag}{scripts}</body></html>""".encode()


def index_page() -> bytes:
    """List digests (newest first) and projects."""
    ratings = load_ratings()
    digest_items = []
    for triage_path in sorted(TRIAGE_DIR.glob("*.jsonl"), reverse=True):
        records = [json.loads(line) for line in triage_path.open()]
        rated = 0
        for record in records:
            rating = ratings.get(record["paperId"]) or {}
            if rating.get("user_tier") or rating.get("note"):
                rated += 1
        name = html.escape(triage_path.stem)
        digest_items.append(
            f'<li><a href="/digest/{name}">{name}</a> '
            f'<span class="muted">{len(records)} papers, {rated} rated</span></li>'
        )
    project_items = []
    for slug in list_projects():
        directory = project_dir(slug)
        title = (directory / "description.md").read_text().splitlines()[0].lstrip("# ")
        feed = load_project_config(directory).get("feed")
        state = project_state(slug)
        details = [text for text in (state, f"feed: {feed}" if feed else None) if text]
        details_text = html.escape(" · " + " · ".join(details)) if details else ""
        project_items.append(
            f'<li><a href="/project/{slug}">{html.escape(title)}</a>'
            f'<span class="muted">{details_text}</span></li>'
        )
    body = (
        "<h1>Literature</h1>"
        '<p><a href="/feeds">Feeds &amp; seeds</a> · <a href="/deepdive/new">New deep dive</a></p>'
        "<h2>Digests</h2><ul>" + "".join(digest_items) + "</ul>"
        "<h2>Deep-dive projects</h2><ul>" + "".join(project_items) + "</ul>"
    )
    return page("Literature", body)


def project_state(slug: str) -> str | None:
    """A short pipeline state for the index ("searching", "awaiting seeds", ...)."""
    pipeline = project_pipeline_data(slug)
    job = pipeline["job"]
    if job and job["state"] == "running":
        return f"running: {job['stages'][job['current']][0]}"
    if job and job["state"] in ("failed", "interrupted"):
        return f"{job['state']} at {job['stages'][job['current']][0]}"
    if pipeline["awaitingSeeds"]:
        return "awaiting seed confirmation"
    return None


def digest_sort_key(record: dict) -> tuple:
    """Order within a tier: flagged authors, then citing-me, then newest first."""
    date = str(record.get("publicationDate") or record.get("year") or "")
    return (not record.get("flaggedAuthors"), "citing_me" not in record["feeds"], date[::-1])


def digest_records(name: str) -> dict[str, dict] | None:
    """Return a digest's triage records keyed by paper ID, or None if it doesn't exist."""
    triage_path = TRIAGE_DIR / f"{name}.jsonl"
    if not DIGEST_NAME_PATTERN.match(name) or not triage_path.exists():
        return None
    with triage_path.open() as handle:
        return {record["paperId"]: record for record in map(json.loads, handle)}


def digest_page(name: str) -> bytes | None:
    """Render one digest; return None if it doesn't exist."""
    records_by_id = digest_records(name)
    if records_by_id is None:
        return None
    records = sorted(records_by_id.values(), key=digest_sort_key)
    all_collections = collections()
    notes = {}
    for record in records:
        record["defaultCollection"] = default_collection(record, all_collections)
        note = read_note(NOTES_DIR, record["paperId"])
        if note:
            notes[record["paperId"]] = note
    ratings = load_ratings()
    library = load_index()
    digest_ratings = {}
    digest_library = {}
    for paper_id in records_by_id:
        if paper_id in ratings:
            digest_ratings[paper_id] = ratings[paper_id]
        if paper_id in library:
            digest_library[paper_id] = library[paper_id]
    data = {
        "context": {"digest": name},
        "papers": records,
        "ratings": digest_ratings,
        "notes": notes,
        "library": digest_library,
        "collections": all_collections,
    }
    model = records[0].get("model", "n/a") if records else "n/a"
    body = (
        '<p class="muted"><a href="/">home</a></p>'
        f"<h1>Digest {html.escape(name)}</h1>"
        f'<p class="muted">{len(records)} papers · triage model: {html.escape(model)} · '
        "choose a tier only where you disagree or feel strongly; changes save automatically.</p>"
        '<div class="toolbar"><button id="expand">Expand all</button>'
        '<button id="collapse">Collapse all</button></div>'
        '<div id="tiers"></div>'
    )
    return page(f"Digest {name}", body, data, "digest.js")


def split_synthesis(text: str) -> tuple[str, dict[str, str]]:
    """Split synthesis.md into its body (no title, no References) and {number: paperId}."""
    body, _, references = text.partition("\n## References")
    citations = {}
    for line in references.splitlines():
        match = REFERENCE_PATTERN.match(line.strip())
        if match:
            citations[match.group(1)] = match.group(2)
    body_lines = [line for line in body.splitlines() if not line.startswith("# ")]
    return "\n".join(body_lines).strip(), citations


def project_page(slug: str) -> bytes | None:
    """Render a deep-dive project; return None if it doesn't exist."""
    directory = project_dir(slug)
    if directory is None:
        return None
    feed = load_project_config(directory).get("feed")
    candidates = load_candidates(directory)
    label_order = {label: index for index, label in enumerate(PROJECT_LABELS)}
    papers = sorted(
        (record for record in candidates.values() if record.get("relevance") in label_order),
        key=lambda record: (
            label_order[record["relevance"]],
            -len(record.get("sources") or []),
            -(record.get("citationCount") or 0),
        ),
    )
    notes = {}
    for record in papers:
        record["defaultCollection"] = slug
        note = read_note(directory / "notes", record["paperId"])
        if note:
            notes[record["paperId"]] = note
    synthesis_path = directory / "synthesis.md"
    synthesis, citations = ("", {})
    if synthesis_path.exists():
        synthesis, citations = split_synthesis(synthesis_path.read_text())
    library = load_index()
    paper_ids = {record["paperId"] for record in papers}
    data = {
        "context": {"project": slug},
        "feed": feed,
        "seeds": [row["paperId"] for row in read_seed_rows(feed)] if feed else [],
        "papers": papers,
        "thumbs": load_thumbs(directory),
        "notes": notes,
        "synthesis": synthesis,
        "citations": citations,
        "library": {paper_id: library[paper_id] for paper_id in paper_ids if paper_id in library},
        "collections": collections(),
        "pipeline": project_pipeline_data(slug),
    }
    title = (directory / "description.md").read_text().splitlines()[0].lstrip("# ")
    feed_text = (
        f"👍 adds a paper to the <code>{html.escape(feed)}</code> feed's seeds, 👎 removes it, "
        "clicking again returns to neutral (undoing the change)."
        if feed
        else "No feed linked (add <code>feed: &lt;name&gt;</code> to project.yaml to enable 👍/👎)."
    )
    body = (
        '<p class="muted"><a href="/">home</a></p>'
        f"<h1>{html.escape(title)}</h1>"
        f'<p class="muted">{len(papers)} relevant papers · {feed_text}</p>'
        '<div class="toolbar"><button id="expand">Expand all</button>'
        '<button id="collapse">Collapse all</button>'
        '<label class="muted"><input type="checkbox" id="autosave" checked> '
        "👍 also saves to library</label></div>"
        '<div id="pipeline"></div><div id="synthesis"></div><div id="papers"></div>'
    )
    return page(title, body, data, "project.js")


class UIHandler(BaseHTTPRequestHandler):
    """Serve pages, static files, and the JSON API."""

    def _send(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        content = None
        if path in ("/", "/index.html"):
            content = index_page()
        elif path.startswith("/digest/"):
            content = digest_page(path.removeprefix("/digest/"))
        elif path.startswith("/project/"):
            content = project_page(path.removeprefix("/project/"))
        elif path == "/feeds":
            content = page("Feeds & seeds", feeds_page_body(), feeds_page_data(), "feeds.js")
        elif path == "/deepdive/new":
            content = page("New deep dive", new_dive_body(), {"context": {}}, "newdive.js")
        elif path.startswith("/static/"):
            name = path.removeprefix("/static/")
            static_path = STATIC_DIR / name
            # serve only plain file names that exist in static/ (no traversal)
            if "/" not in name and static_path.suffix in STATIC_TYPES and static_path.exists():
                self._send(200, static_path.read_bytes(), STATIC_TYPES[static_path.suffix])
                return
        if content is None:
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, content, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            request = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "bad JSON"})
            return
        if not isinstance(request, dict):
            self._send_json(400, {"error": "expected a JSON object"})
            return
        if self.path in ROUTES:
            self._handle_managed(ROUTES[self.path], request)
            return
        if self.path == "/api/save" and "seeds" in request:
            self._handle_managed(
                lambda body: self._save_result(
                    fetch_record(str(body.get("paperId") or "")), body.get("collection")
                ),
                request,
            )
            return
        if "digest" in request:
            records = digest_records(str(request["digest"]))
            directory = None
        elif "project" in request:
            directory = project_dir(str(request["project"]))
            records = load_candidates(directory) if directory else None
        else:
            records = None
        if records is None:
            self._send_json(400, {"error": "unknown digest or project"})
            return
        record = records.get(request.get("paperId"))
        if record is None:
            self._send_json(400, {"error": "unknown paper"})
            return

        if self.path == "/api/save":
            self._handle_save(record, request.get("collection"))
        elif self.path == "/api/rate" and "digest" in request:
            user_tier = request.get("user_tier")
            if user_tier not in (None, 1, 2, 3, 4):
                self._send_json(400, {"error": "bad tier"})
                return
            note = str(request.get("note") or "")[:2000]
            append_rating(record, user_tier, note, str(request["digest"]))
            self._send_json(200, {"ok": True})
        elif self.path == "/api/thumb" and directory is not None:
            try:
                entry = set_thumb(directory, record, request.get("thumb"))
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return
            self._send_json(200, {"entry": entry})
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_save(self, record: dict, collection: str | None) -> None:
        """Save `record` to `collection`, or unsave it when `collection` is None."""
        self._handle_managed(lambda body: self._save_result(record, collection), {})

    @staticmethod
    def _save_result(record: dict, collection: str | None) -> tuple[int, dict]:
        if collection is None:
            unsave_paper(record["paperId"])
            return 200, {"row": None}
        if collection not in collections():
            raise ApiError("unknown collection")
        try:
            row = save_paper(record, collection)
        except LookupError as error:
            raise ApiError("no BibTeX found", 404) from error
        return 200, {"row": row}

    def _handle_managed(self, handler, request: dict) -> None:
        """Run a `(status, payload)` handler, mapping errors to JSON error responses."""
        try:
            status, payload = handler(request)
        except ApiError as error:
            status, payload = error.status, {"error": str(error)}
        except urllib.error.HTTPError as error:
            status, payload = 502, {"error": f"Semantic Scholar returned HTTP {error.code}"}
        except urllib.error.URLError as error:
            status, payload = 502, {"error": f"network error: {error.reason}"}
        self._send_json(status, payload)

    def log_message(self, format: str, *args) -> None:
        # keep the terminal quiet except for errors
        if args and str(args[1]).startswith(("4", "5")):
            print(format % args, file=sys.stderr)
