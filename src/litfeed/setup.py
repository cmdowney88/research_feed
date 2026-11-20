"""First-run setup: the data directory, API keys, the user's Semantic Scholar profile, a drafted
taste profile, and the weekly schedule. Used by `scripts/init_data.py` and the UI's /setup page.
"""

import os
import plistlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from litfeed.feeds import CONFIG_PATH, SEEDS_DIR, load_config, read_seed_rows
from litfeed.llm import run_claude
from litfeed.paths import CODE_ROOT, DATA_ROOT, PROMPTS_DIR
from litfeed.s2 import S2Client

ENV_PATH = DATA_ROOT / ".env"
PROFILE_PATH = DATA_ROOT / "taste" / "profile.md"
PROFILE_TEMPLATE = CODE_ROOT / "examples" / "profile.md"
TEMPLATES = {
    "configs/feeds.yaml": "examples/feeds.yaml",
    "taste/profile.md": "examples/profile.md",
}
DIRECTORIES = ["seeds", "projects", "library", "notes", "triage", "digests"]
GITIGNORE = "cache/\nfetches/\nlogs/\nlibrary/pdfs/\n.env\n"
ENV_KEYS = ("S2_API_KEY", "ANTHROPIC_API_KEY", "LITFEED_PYTHON")
LAUNCHD_LABEL = "local.litfeed.weekly"
LAUNCHD_TEMPLATE = CODE_ROOT / "configs" / "launchd" / f"{LAUNCHD_LABEL}.plist"
LAUNCHD_TARGET = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
PROFILE_SCHEMA = {
    "type": "object",
    "properties": {"profile": {"type": "string"}},
    "required": ["profile"],
    "additionalProperties": False,
}
MAX_PROFILE_PAPERS = 40
MAX_ABSTRACT_CHARS = 900


# ---------- data directory and .env ----------


def init_data_dir() -> list[str]:
    """Create the data directory from `examples/` (never overwriting); return what was created."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    created = []
    for target, source in TEMPLATES.items():
        path = DATA_ROOT / target
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(CODE_ROOT / source, path)
            created.append(target)
    for directory in DIRECTORIES:
        (DATA_ROOT / directory).mkdir(exist_ok=True)
    gitignore = DATA_ROOT / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE)
        created.append(".gitignore")
    if not ENV_PATH.exists():
        update_env({"S2_API_KEY": "", "ANTHROPIC_API_KEY": "", "LITFEED_PYTHON": sys.executable})
        created.append(".env")
    return created


def read_env() -> dict[str, str]:
    """Parse KEY=VALUE lines of the data directory's `.env` ({} if absent)."""
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            key, separator, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if separator and key and not key.startswith("#"):
                values[key] = value.strip().strip("\"'")
    return values


def update_env(values: dict[str, str]) -> None:
    """Set keys in `.env`, keeping other lines and comments; the file is readable only by you.

    Also updates this process's environment, so the running server uses new keys at once.
    """
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    remaining = dict(values)
    for index, line in enumerate(lines):
        key = line.partition("=")[0].strip().removeprefix("export ").strip()
        if key in remaining:
            lines[index] = f"{key}={remaining.pop(key)}"
    lines += [f"{key}={value}" for key, value in remaining.items()]
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n")
    ENV_PATH.chmod(0o600)
    for key, value in values.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def load_env_into_process() -> None:
    """Fill unset environment variables from `.env` (the shell's own values win)."""
    for key, value in read_env().items():
        if value:
            os.environ.setdefault(key, value)


def key_status() -> dict[str, dict]:
    """Whether each key is set (from the environment or `.env`), with its last 4 characters."""
    stored = read_env()
    status = {}
    for key in ENV_KEYS:
        value = os.environ.get(key) or stored.get(key) or ""
        status[key] = {"set": bool(value), "hint": f"…{value[-4:]}" if len(value) > 8 else ""}
    return status


# ---------- key and tool checks ----------


def test_s2_key(api_key: str) -> tuple[bool, str]:
    """Make one small S2 request with the key; return (ok, message)."""
    request = urllib.request.Request(
        "https://api.semanticscholar.org/graph/v1/paper/search?query=transformer&limit=1",
        headers={"x-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True, "Semantic Scholar accepted the key"
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return False, f"Semantic Scholar rejected the key (HTTP {error.code})"
        if error.code == 429:
            return True, "rate-limited just now (HTTP 429), which says nothing about the key"
        return False, f"Semantic Scholar returned HTTP {error.code}"
    except urllib.error.URLError as error:
        return False, f"network error: {error.reason}"


def test_anthropic_key(api_key: str) -> tuple[bool, str]:
    """List models with the key (no tokens are spent); return (ok, message)."""
    try:
        import anthropic
    except ImportError:
        return False, "install the `anthropic` package to test the key here"
    client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=30.0)
    try:
        client.models.list(limit=1)
    except anthropic.AuthenticationError:
        return False, "Anthropic rejected the key (HTTP 401)"
    except anthropic.PermissionDeniedError:
        return False, "the key lacks permission to list models (HTTP 403)"
    except anthropic.APIStatusError as error:
        return False, f"Anthropic returned HTTP {error.status_code}"
    except anthropic.APIConnectionError:
        return False, "network error reaching Anthropic"
    return True, "Anthropic accepted the key"


def tool_status() -> dict[str, str | None]:
    """Paths of the external programs the pipeline uses (None when missing)."""
    extra_path = os.pathsep.join([str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin"])
    search_path = os.environ.get("PATH", "") + os.pathsep + extra_path
    return {
        "claude": shutil.which("claude", path=search_path),
        "pdftotext": shutil.which("pdftotext", path=search_path),
    }


# ---------- taste profile ----------


def profile_status() -> dict:
    """Whether the taste profile exists and has been changed from the template."""
    if not PROFILE_PATH.exists():
        return {"exists": False, "customized": False}
    customized = PROFILE_PATH.read_text().strip() != PROFILE_TEMPLATE.read_text().strip()
    return {"exists": True, "customized": customized}


def draft_profile(
    author_id: str,
    notes: str,
    client: S2Client,
    model: str = "sonnet",
) -> tuple[str, float | None]:
    """Draft a taste profile from the author's publications and the user's notes.

    Args:
        author_id: The user's S2 author ID.
        notes: Free text from the user (current projects, pivots, dislikes); takes priority.
        client: S2 client.
        model: Model alias for `claude -p`.

    Returns:
        The drafted Markdown and the call's cost in USD (None if unreported).

    Raises:
        RuntimeError: If S2 returns no papers or the Claude call fails.
    """
    payload = client.get(
        f"/author/{author_id}/papers",
        {"fields": "title,year,venue,abstract", "limit": 100},
        use_cache=False,
    )
    papers = sorted(
        payload.get("data") or [],
        key=lambda paper: -(paper.get("year") or 0),
    )[:MAX_PROFILE_PAPERS]
    if not papers:
        raise RuntimeError("Semantic Scholar lists no papers for that author ID")
    entries = []
    for paper in papers:
        abstract = (paper.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
        venue = f", {paper['venue']}" if paper.get("venue") else ""
        entries.append(
            f"- {paper.get('title')} ({paper.get('year') or 'n.d.'}{venue})"
            + (f"\n  {abstract}" if abstract else "")
        )
    user_message = (
        "# The researcher's notes (take precedence over what the papers suggest)\n\n"
        + (notes.strip() or "(none)")
        + "\n\n# The researcher's publications, newest first\n\n"
        + "\n".join(entries)
    )
    system_prompt = (PROMPTS_DIR / "profile_draft.md").read_text().replace(
        "{template}", PROFILE_TEMPLATE.read_text()
    )
    result = run_claude(system_prompt, user_message, PROFILE_SCHEMA, model=model)
    if result.output is None:
        raise RuntimeError(result.error or "the Claude call failed")
    return result.output["profile"], result.cost_usd


# ---------- weekly schedule (macOS launchd) ----------


def schedule_status() -> dict:
    """Whether the weekly launchd job is installed, and when it runs."""
    if sys.platform != "darwin":
        return {"supported": False, "installed": False}
    if not LAUNCHD_TARGET.exists():
        return {"supported": True, "installed": False}
    with LAUNCHD_TARGET.open("rb") as handle:
        plist = plistlib.load(handle)
    interval = plist.get("StartCalendarInterval") or {}
    data_dir = (plist.get("EnvironmentVariables") or {}).get("LITFEED_DATA")
    # launchd allows one job under this label per user, possibly for another data directory
    for_this_data = data_dir is not None and Path(data_dir).resolve() == DATA_ROOT
    return {
        "supported": True,
        "installed": for_this_data,
        "otherDataDir": None if for_this_data else data_dir,
        "weekday": interval.get("Weekday"),
        "hour": interval.get("Hour"),
    }


def install_schedule(weekday: int, hour: int) -> dict:
    """Install (or replace) the weekly launchd job for this checkout and data directory.

    Args:
        weekday: 0 (Sunday) to 6 (Saturday), as launchd counts.
        hour: 0-23, local time.

    Returns:
        The new `schedule_status()`.

    Raises:
        ValueError: On a bad weekday or hour.
        RuntimeError: If not on macOS or launchctl fails.
    """
    if sys.platform != "darwin":
        raise RuntimeError("scheduling uses launchd, which is macOS only")
    if weekday not in range(7) or hour not in range(24):
        raise ValueError("weekday must be 0-6 and hour 0-23")
    template = LAUNCHD_TEMPLATE.read_text()
    template = template.replace("__REPO__", str(CODE_ROOT)).replace("__DATA__", str(DATA_ROOT))
    plist = plistlib.loads(template.encode())
    plist["StartCalendarInterval"] = {"Weekday": weekday, "Hour": hour, "Minute": 0}
    (DATA_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    LAUNCHD_TARGET.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    # unload any previous copy so the new schedule takes effect
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"],
        capture_output=True,
    )
    with LAUNCHD_TARGET.open("wb") as handle:
        plistlib.dump(plist, handle)
    completed = subprocess.run(
        ["launchctl", "bootstrap", domain, str(LAUNCHD_TARGET)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {completed.stderr.strip()}")
    return schedule_status()


# ---------- overall status ----------


def feed_status() -> dict:
    """Feeds with their seed counts, and whether bootstrap candidates exist."""
    config = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else {"feeds": {}}
    counts = {name: len(read_seed_rows(name)) for name in config.get("feeds") or {}}
    return {
        "seedCounts": counts,
        "seededFeeds": sum(1 for count in counts.values() if count),
        "authorId": str(config.get("author_id") or ""),
        "candidates": (SEEDS_DIR / "candidates.tsv").exists(),
    }


def setup_status() -> dict:
    """Everything the /setup page shows, plus `ready`: whether a weekly run can work."""
    keys = key_status()
    tools = tool_status()
    profile = profile_status()
    feeds = feed_status()
    ready = (
        keys["ANTHROPIC_API_KEY"]["set"]
        and tools["claude"] is not None
        and profile["customized"]
        and feeds["seededFeeds"] > 0
    )
    return {
        "dataDir": str(DATA_ROOT),
        "dataDirFromEnv": bool(os.environ.get("LITFEED_DATA")),
        "keys": keys,
        "tools": tools,
        "profile": profile,
        "feeds": feeds,
        "schedule": schedule_status(),
        "digests": len(list((DATA_ROOT / "triage").glob("*.jsonl"))),
        "ready": ready,
    }
