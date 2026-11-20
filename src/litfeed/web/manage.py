"""Feed and deep-dive management for the web UI: the /feeds and /deepdive/new pages and the
JSON endpoints behind them.

Every handler takes the parsed request body and returns `(status, payload)`; `server.py`
routes requests here and sends the result. Handlers raise `ApiError` for bad input.
"""

import csv
import re
import threading

from litfeed.config_edit import add_feed, add_flagged_author
from litfeed.feeds import add_seed, load_config, read_seed_rows, remove_seed, seed_row
from litfeed.feeds import write_seed_rows
from litfeed.jobs import after_seed_stages, job_status, resume_job, search_stages, start_job
from litfeed.library import load_index
from litfeed.projects import PROJECTS_DIR, SLUG_PATTERN, list_projects, load_candidates
from litfeed.projects import load_project_config, project_dir
from litfeed.resolve import PAPER_FIELDS, paper_record, resolve_lines
from litfeed.s2 import S2Client

AUTHOR_FIELDS = "name,affiliations,paperCount,hIndex,papers.title,papers.year"
MAX_PASTED_LINES = 100
PROJECT_SEED_FIELDS = ["paperId", "year", "signals", "aspect", "title"]

# one S2 client for the server; the lock keeps its throttle honest across request threads
_client = S2Client(min_interval=1.1)
_S2_LOCK = threading.Lock()


class ApiError(Exception):
    """A request the API rejects; `status` is the HTTP status to send."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _feed_names() -> list[str]:
    return list(load_config()["feeds"])


def _require_feed(name) -> str:
    if name not in _feed_names():
        raise ApiError(f"unknown feed: {name!r}")
    return name


def _clean_rows(rows) -> list[dict]:
    """Validate seed rows sent by the page (paperId, year, source, title)."""
    if not isinstance(rows, list) or not rows:
        raise ApiError("no papers given")
    cleaned = []
    for row in rows:
        paper_id = str((row or {}).get("paperId") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", paper_id):
            raise ApiError(f"bad paper ID: {paper_id!r}")
        cleaned.append(
            {
                "paperId": paper_id,
                "year": str(row.get("year") or ""),
                "source": str(row.get("source") or "ui")[:80],
                "title": " ".join(str(row.get("title") or "").split())[:400],
            }
        )
    return cleaned


def _project_title(slug: str) -> str:
    return (PROJECTS_DIR / slug / "description.md").read_text().splitlines()[0].lstrip("# ")


def _project_seed_rows(slug: str) -> list[dict]:
    path = PROJECTS_DIR / slug / "seeds.tsv"
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [
            {**row, "source": f"deepdive:{slug}"}
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def fetch_record(paper_id: str) -> dict:
    """Fetch full metadata for one paper from S2 (cached), for saving to the library."""
    with _S2_LOCK:
        papers = _client.paper_batch([paper_id], PAPER_FIELDS)
    if not papers:
        raise ApiError("paper not found on S2", 404)
    return paper_record(papers[0])


# ---------- pages ----------


def feeds_page_data() -> dict:
    """Data for /feeds: feeds with seeds, flagged authors, projects, library collections."""
    config = load_config()
    library = load_index()
    feeds = []
    seed_ids = set()
    for name, spec in config["feeds"].items():
        rows = read_seed_rows(name)
        seed_ids.update(row["paperId"] for row in rows)
        feeds.append(
            {
                "name": name,
                "priority": spec.get("priority"),
                "description": spec.get("description"),
                "seeds": rows,
                "negatives": len(read_seed_rows(f"{name}.negative")),
            }
        )
    projects = []
    for slug in list_projects():
        projects.append(
            {
                "slug": slug,
                "title": _project_title(slug),
                "feed": load_project_config(PROJECTS_DIR / slug).get("feed"),
                "seeds": _project_seed_rows(slug),
            }
        )
    collection_counts = {}
    for row in library.values():
        collection_counts[row["collection"]] = collection_counts.get(row["collection"], 0) + 1
    return {
        "context": {"seeds": True},
        "feeds": feeds,
        "flagged": {name: list(ids) for name, ids in (config.get("flagged_authors") or {}).items()},
        "projects": projects,
        "libraryCollections": collection_counts,
        "library": {paper_id: library[paper_id] for paper_id in seed_ids if paper_id in library},
        "collections": [feed["name"] for feed in feeds] + ["general"] + list_projects(),
    }


def feeds_page_body() -> str:
    return (
        '<p class="muted"><a href="/">home</a></p>'
        "<h1>Feeds &amp; seeds</h1>"
        '<p class="muted">Seeds drive the weekly recommendations. Edits write '
        "<code>seeds/&lt;feed&gt;.tsv</code> and <code>configs/feeds.yaml</code> immediately "
        "(commit them when you're happy).</p>"
        '<div class="toolbar"><button id="expand">Expand all</button>'
        '<button id="collapse">Collapse all</button></div>'
        '<div id="feeds"></div><div id="flagged"></div><div id="new-feed"></div>'
    )


def new_dive_body() -> str:
    return (
        '<p class="muted"><a href="/">home</a></p>'
        "<h1>New deep dive</h1>"
        '<p class="muted">Describe the project: the setting, the questions, the kinds of '
        "literature to look for, and what is out of scope. Everything downstream (queries, "
        "relevance scoring, notes, synthesis) is judged against this text, so specifics help. "
        "The search stage takes ~5–10 minutes and ~$1–2; you then confirm seeds before "
        "recommendations, notes, and synthesis (~$3–5 more).</p>"
        '<form id="dive-form" class="card stack">'
        '<label>Title <input id="dive-title" required maxlength="150" '
        'placeholder="e.g. Considerations for ASR in multi-transcriber documentation"></label>'
        '<label>Slug <input id="dive-slug" required maxlength="60" pattern="[0-9a-z][0-9a-z_-]*">'
        '<span class="muted"> (folder name under projects/; lowercase, digits, - and _)</span>'
        "</label>"
        '<label>Description <textarea id="dive-text" required rows="16"></textarea></label>'
        '<div><button type="submit" class="primary">Start search</button> '
        '<span id="dive-status" class="status"></span></div></form>'
    )


def project_pipeline_data(slug: str) -> dict:
    """Pipeline state for a project page: job status and, at the checkpoint, seed choices."""
    directory = PROJECTS_DIR / slug
    status = job_status(slug)
    proposed_path = directory / "proposed_seeds.tsv"
    awaiting_seeds = (
        proposed_path.exists()
        and not (directory / "seeds.tsv").exists()
        and not (status and status["state"] == "running")
    )
    proposed = []
    related = []
    if awaiting_seeds:
        with proposed_path.open(newline="") as handle:
            proposed = list(csv.DictReader(handle, delimiter="\t"))
        candidates = load_candidates(directory)
        related = sorted(
            (record for record in candidates.values() if record.get("relevance") == "related"),
            key=lambda record: (
                -len(record.get("sources") or []),
                -(record.get("citationCount") or 0),
            ),
        )[:40]
        related = [
            {
                "paperId": record["paperId"],
                "year": record.get("year") or "",
                "signals": len(record.get("sources") or []),
                "aspect": record.get("aspect") or "",
                "title": record.get("title") or "",
            }
            for record in related
        ]
    return {
        "job": status,
        "awaitingSeeds": awaiting_seeds,
        "proposed": proposed,
        "related": related,
        "hasSynthesis": (directory / "synthesis.md").exists(),
    }


# ---------- API ----------


def api_resolve(request: dict) -> tuple[int, dict]:
    """Resolve pasted identifiers; mark which feeds already have each paper."""
    lines = str(request.get("text") or "").splitlines()
    lines = [line for line in lines if line.strip()]
    if not lines:
        raise ApiError("nothing to look up")
    if len(lines) > MAX_PASTED_LINES:
        raise ApiError(f"at most {MAX_PASTED_LINES} lines at a time")
    with _S2_LOCK:
        results = resolve_lines(lines, _client, "title,year,venue,authors")
    in_feeds = {}
    for name in _feed_names():
        for row in read_seed_rows(name):
            in_feeds.setdefault(row["paperId"], []).append(name)
    payload = []
    for result in results:
        paper = result["paper"]
        summary = None
        if paper:
            summary = {
                "paperId": paper["paperId"],
                "title": paper.get("title"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "authors": [author.get("name") for author in paper.get("authors") or []][:4],
                "inFeeds": in_feeds.get(paper["paperId"], []),
            }
        payload.append({"input": result["input"], "how": result["how"], "paper": summary})
    return 200, {"results": payload}


def api_seeds_add(request: dict) -> tuple[int, dict]:
    feed = _require_feed(request.get("feed"))
    added = [row for row in _clean_rows(request.get("rows")) if add_seed(feed, row)]
    return 200, {"added": added, "seeds": read_seed_rows(feed)}


def api_seeds_remove(request: dict) -> tuple[int, dict]:
    feed = _require_feed(request.get("feed"))
    removed = remove_seed(feed, str(request.get("paperId") or ""))
    if removed is None:
        raise ApiError("not a seed of this feed")
    return 200, {"removed": removed, "seeds": read_seed_rows(feed)}


def api_collection_rows(request: dict) -> tuple[int, dict]:
    """Seed rows for every paper saved to a library collection."""
    collection = str(request.get("collection") or "")
    paper_ids = [
        paper_id for paper_id, row in load_index().items() if row["collection"] == collection
    ]
    if not paper_ids:
        raise ApiError("no papers in that collection")
    with _S2_LOCK:
        papers = _client.paper_batch(paper_ids, "title,year")
    rows = [seed_row(paper, f"library:{collection}") for paper in papers]
    return 200, {"rows": rows}


def api_feed_create(request: dict) -> tuple[int, dict]:
    """Create a feed (config entry + seed file), optionally linking a project to it."""
    name = str(request.get("name") or "").strip()
    rows = _clean_rows(request.get("rows"))
    unique_rows = list({row["paperId"]: row for row in reversed(rows)}.values())[::-1]
    link_project = request.get("linkProject")
    if link_project and project_dir(str(link_project)) is None:
        raise ApiError("unknown project")
    try:
        add_feed(name, str(request.get("description") or ""), str(request.get("priority")))
    except ValueError as error:
        raise ApiError(str(error)) from error
    write_seed_rows(name, unique_rows)
    if link_project:
        config_path = PROJECTS_DIR / str(link_project) / "project.yaml"
        if not load_project_config(config_path.parent).get("feed"):
            config_path.write_text(f"feed: {name}\n")
    return 200, {"feed": name, "seeds": len(unique_rows)}


def api_author_search(request: dict) -> tuple[int, dict]:
    query = " ".join(str(request.get("query") or "").split())
    if not query:
        raise ApiError("enter a name")
    with _S2_LOCK:
        payload = _client.get(
            "/author/search",
            {"query": query, "fields": AUTHOR_FIELDS, "limit": 15},
        )
    flagged_ids = {
        str(author_id)
        for ids in (load_config().get("flagged_authors") or {}).values()
        for author_id in ids
    }
    authors = []
    for author in payload.get("data") or []:
        papers = sorted(
            author.get("papers") or [],
            key=lambda paper: -(paper.get("year") or 0),
        )
        authors.append(
            {
                "authorId": author["authorId"],
                "name": author.get("name"),
                "affiliations": author.get("affiliations") or [],
                "paperCount": author.get("paperCount"),
                "hIndex": author.get("hIndex"),
                "recent": [
                    f"{paper.get('title')} ({paper.get('year') or 'n.d.'})"
                    for paper in papers[:3]
                ],
                "flagged": author["authorId"] in flagged_ids,
            }
        )
    return 200, {"authors": authors}


def api_author_add(request: dict) -> tuple[int, dict]:
    ids = [str(author_id) for author_id in request.get("ids") or []]
    try:
        all_ids = add_flagged_author(str(request.get("name") or ""), ids)
    except ValueError as error:
        raise ApiError(str(error)) from error
    return 200, {"ids": all_ids}


def api_dive_create(request: dict) -> tuple[int, dict]:
    """Create `projects/<slug>/description.md` and start the search stage."""
    slug = str(request.get("slug") or "").strip()
    title = " ".join(str(request.get("title") or "").split())
    text = str(request.get("description") or "").strip()
    if not SLUG_PATTERN.match(slug):
        raise ApiError("bad slug (lowercase letters, digits, - and _)")
    if (PROJECTS_DIR / slug).exists():
        raise ApiError(f"projects/{slug} already exists")
    if not title or len(text) < 200:
        raise ApiError("give a title and a description of at least a few sentences")
    directory = PROJECTS_DIR / slug
    directory.mkdir(parents=True)
    (directory / "description.md").write_text(f"# {title}\n\n{text}\n")
    try:
        start_job(slug, search_stages(slug))
    except RuntimeError as error:
        raise ApiError(f"{error}; project created, start it from its page later", 409) from error
    return 200, {"slug": slug}


def api_dive_seeds(request: dict) -> tuple[int, dict]:
    """Write the confirmed seeds and start recommend → notes → synthesize."""
    slug = str(request.get("project") or "")
    directory = project_dir(slug)
    if directory is None:
        raise ApiError("unknown project")
    if (directory / "seeds.tsv").exists():
        raise ApiError("seeds already confirmed")
    paper_ids = [str(paper_id) for paper_id in request.get("paperIds") or []]
    candidates = load_candidates(directory)
    rows = []
    for paper_id in paper_ids:
        record = candidates.get(paper_id)
        if record is None:
            raise ApiError(f"not a candidate: {paper_id}")
        rows.append(
            {
                "paperId": paper_id,
                "year": record.get("year") or "",
                "signals": len(record.get("sources") or []),
                "aspect": record.get("aspect") or "",
                "title": record.get("title") or "",
            }
        )
    if not rows:
        raise ApiError("pick at least one seed")
    with (directory / "seeds.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROJECT_SEED_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    try:
        start_job(slug, after_seed_stages(slug))
    except RuntimeError as error:
        (directory / "seeds.tsv").unlink()
        raise ApiError(str(error), 409) from error
    return 200, {"seeds": len(rows)}


def api_dive_resume(request: dict) -> tuple[int, dict]:
    slug = str(request.get("project") or "")
    if project_dir(slug) is None:
        raise ApiError("unknown project")
    try:
        if job_status(slug) is None:
            start_job(slug, search_stages(slug))
        else:
            resume_job(slug)
    except RuntimeError as error:
        raise ApiError(str(error), 409) from error
    return 200, {"ok": True}


def api_job(request: dict) -> tuple[int, dict]:
    slug = str(request.get("project") or "")
    if project_dir(slug) is None:
        raise ApiError("unknown project")
    return 200, {"job": job_status(slug)}


ROUTES = {
    "/api/resolve": api_resolve,
    "/api/seeds/add": api_seeds_add,
    "/api/seeds/remove": api_seeds_remove,
    "/api/collection-rows": api_collection_rows,
    "/api/feeds/create": api_feed_create,
    "/api/authors/search": api_author_search,
    "/api/authors/add": api_author_add,
    "/api/deepdive/create": api_dive_create,
    "/api/deepdive/seeds": api_dive_seeds,
    "/api/deepdive/resume": api_dive_resume,
    "/api/job": api_job,
}
