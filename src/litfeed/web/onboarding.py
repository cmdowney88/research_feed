"""The /setup page: a checklist that walks a new user from an empty data directory to a first
digest. Every step is also doable by hand (see the README); this page just does it in place.

Handlers follow `litfeed.web.manage`: they take the request body and return `(status, payload)`,
raising `ApiError` for bad input.
"""

import csv
import os
import sys

from litfeed import setup
from litfeed.config_edit import set_author_id
from litfeed.feeds import SEEDS_DIR, load_config, read_seed_rows
from litfeed.jobs import job_status, start_job
from litfeed.web import manage
from litfeed.web.manage import ApiError

SETUP_JOBS = ("setup-seeds", "weekly")
MAX_CANDIDATES = 150


def setup_page_data() -> dict:
    profile_text = setup.PROFILE_PATH.read_text() if setup.PROFILE_PATH.exists() else ""
    return {
        "context": {},
        "status": setup.setup_status(),
        "profileText": profile_text,
        "jobs": {name: job_status(name) for name in SETUP_JOBS},
        "platform": sys.platform,
    }


def setup_page_body() -> str:
    return (
        '<p class="muted"><a href="/">home</a></p>'
        "<h1>Setup</h1>"
        '<p class="muted">Each step saves as you go and can be revisited any time. Steps marked '
        "optional can be skipped.</p>"
        '<div id="setup"></div>'
    )


def _author_id() -> str:
    author_id = str(load_config().get("author_id") or "")
    if not author_id:
        raise ApiError("set your Semantic Scholar profile first (step 3)")
    return author_id


def api_status(request: dict) -> tuple[int, dict]:
    return 200, {
        "status": setup.setup_status(),
        "jobs": {name: job_status(name) for name in SETUP_JOBS},
    }


def api_keys(request: dict) -> tuple[int, dict]:
    """Save API keys to `.env`; blank fields are left unchanged."""
    values = {}
    for key in ("S2_API_KEY", "ANTHROPIC_API_KEY"):
        value = str(request.get(key) or "").strip()
        if value:
            if any(character.isspace() for character in value) or len(value) > 300:
                raise ApiError(f"{key} doesn't look like a key")
            values[key] = value
    if not setup.read_env().get("LITFEED_PYTHON"):
        values["LITFEED_PYTHON"] = sys.executable
    if not values:
        raise ApiError("enter a key to save")
    setup.update_env(values)
    if "S2_API_KEY" in values:
        # let the UI's own S2 client use the new key immediately
        manage._client.api_key = values["S2_API_KEY"]
    return 200, {"keys": setup.key_status()}


def api_test_key(request: dict) -> tuple[int, dict]:
    """Test the key typed into the form, or the saved one if the field is blank."""
    which = request.get("which")
    if which not in ("S2_API_KEY", "ANTHROPIC_API_KEY"):
        raise ApiError("unknown key")
    value = str(request.get("value") or "").strip()
    value = value or os.environ.get(which) or setup.read_env().get(which) or ""
    if not value:
        raise ApiError("no key to test")
    test = setup.test_s2_key if which == "S2_API_KEY" else setup.test_anthropic_key
    ok, message = test(value)
    return 200, {"ok": ok, "message": message}


def api_author(request: dict) -> tuple[int, dict]:
    try:
        set_author_id(str(request.get("authorId") or ""))
    except ValueError as error:
        raise ApiError(str(error)) from error
    return 200, {"status": setup.setup_status()}


def api_draft_profile(request: dict) -> tuple[int, dict]:
    author_id = _author_id()
    notes = str(request.get("notes") or "")[:4000]
    try:
        with manage._S2_LOCK:
            text, cost = setup.draft_profile(author_id, notes, manage._client)
    except RuntimeError as error:
        raise ApiError(str(error), 502) from error
    return 200, {"profile": text, "cost": cost}


def api_profile(request: dict) -> tuple[int, dict]:
    text = str(request.get("text") or "")
    if len(text.strip()) < 200:
        raise ApiError("the profile is too short to guide triage")
    setup.PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    setup.PROFILE_PATH.write_text(text.rstrip() + "\n")
    return 200, {"status": setup.setup_status()}


def api_bootstrap(request: dict) -> tuple[int, dict]:
    """Rank the papers the user cites (scripts/seed_from_author.py) as seed candidates."""
    author_id = _author_id()
    excluded = [str(paper_id) for paper_id in load_config().get("excluded_own_papers") or []]
    arguments = ["--author-id", author_id] + (["--exclude", *excluded] if excluded else [])
    try:
        start_job("setup-seeds", [arguments], script="seed_from_author.py")
    except RuntimeError as error:
        raise ApiError(str(error), 409) from error
    return 200, {"job": job_status("setup-seeds")}


def api_candidates(request: dict) -> tuple[int, dict]:
    """The top bootstrap candidates, marked with the feeds that already have them."""
    path = SEEDS_DIR / "candidates.tsv"
    if not path.exists():
        raise ApiError("no candidates yet: run the bootstrap first")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))[:MAX_CANDIDATES]
    in_feeds = {}
    for name in load_config()["feeds"]:
        for row in read_seed_rows(name):
            in_feeds.setdefault(row["paperId"], []).append(name)
    candidates = [
        {
            "paperId": row["paperId"],
            "year": row.get("year") or "",
            "title": row.get("title") or "",
            "score": row.get("score"),
            "citedIn": row.get("n_cited_in"),
            "inFeeds": in_feeds.get(row["paperId"], []),
        }
        for row in rows
    ]
    return 200, {"candidates": candidates}


def api_schedule(request: dict) -> tuple[int, dict]:
    try:
        schedule = setup.install_schedule(int(request.get("weekday")), int(request.get("hour")))
    except (TypeError, ValueError) as error:
        raise ApiError(str(error)) from error
    except RuntimeError as error:
        raise ApiError(str(error), 500) from error
    return 200, {"schedule": schedule}


def api_run_weekly(request: dict) -> tuple[int, dict]:
    """Run scripts/weekly.sh now (fetch, triage, notes, digest) as a background job (macOS)."""
    if sys.platform != "darwin":
        raise ApiError("the one-click run uses scripts/weekly.sh, which is macOS-only for now")
    if not setup.setup_status()["ready"]:
        raise ApiError("finish steps 2, 4, and 5 first (keys, profile, a seeded feed)")
    try:
        start_job("weekly", [[]], script="weekly.sh")
    except RuntimeError as error:
        raise ApiError(str(error), 409) from error
    return 200, {"job": job_status("weekly")}


def api_named_job(request: dict) -> tuple[int, dict]:
    name = request.get("name")
    if name not in SETUP_JOBS:
        raise ApiError("unknown job")
    return 200, {"job": job_status(name)}


ROUTES = {
    "/api/setup/status": api_status,
    "/api/setup/keys": api_keys,
    "/api/setup/test-key": api_test_key,
    "/api/setup/author": api_author,
    "/api/setup/draft-profile": api_draft_profile,
    "/api/setup/profile": api_profile,
    "/api/setup/bootstrap": api_bootstrap,
    "/api/setup/candidates": api_candidates,
    "/api/setup/schedule": api_schedule,
    "/api/setup/run-weekly": api_run_weekly,
    "/api/setup/job": api_named_job,
}
