"""Run scripts in the background for the web UI (deep-dive stages, setup, the weekly run).

A job is a list of argument lists for one script in `scripts/` (by default `deep_dive.py`), run
one after another in subprocesses. Its status lives in `logs/jobs/<name>.json` and its output in
`logs/jobs/<name>.log` in the data directory (gitignored), so pages can poll them. Deep-dive
jobs are named by project slug; setup uses `setup-seeds` and `weekly`. Only one job runs at a
time: concurrent jobs would share the Semantic Scholar rate limit and mostly trade 429 retries.

Stages run in the server's process group, so stopping the server stops a running stage; the
job then shows as interrupted and can be resumed from the stage it was on (S2 lookups are
cached, so a rerun mostly repeats only LLM calls).
"""

import datetime
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from litfeed.paths import CODE_ROOT, DATA_ROOT

JOBS_DIR = DATA_ROOT / "logs" / "jobs"
SCRIPTS_DIR = CODE_ROOT / "scripts"
ENV_PATH = DATA_ROOT / ".env"

_JOBS_LOCK = threading.Lock()
_running: dict[str, threading.Thread] = {}


def search_stages(slug: str) -> list[list[str]]:
    """Stages up to the seed checkpoint."""
    return [["search", slug]]


def after_seed_stages(slug: str, notes: int = 15) -> list[list[str]]:
    """Stages after the user confirms seeds."""
    return [["recommend", slug], ["notes", slug, "--top", str(notes)], ["synthesize", slug]]


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _status_path(slug: str) -> Path:
    return JOBS_DIR / f"{slug}.json"


def _write_status(slug: str, status: dict) -> None:
    """Write the status atomically, so a concurrent reader never sees a half-written file."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _status_path(slug).with_suffix(".json.tmp")
    temporary.write_text(json.dumps(status, indent=1))
    os.replace(temporary, _status_path(slug))


def _environment() -> dict[str, str]:
    """The server's environment plus KEY=VALUE lines from `.env` (API keys), with
    `LITFEED_DATA` pinned so every job uses this server's data directory."""
    environment = dict(os.environ)
    environment["LITFEED_DATA"] = str(DATA_ROOT)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            key, separator, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if separator and key and not key.startswith("#"):
                environment.setdefault(key, value.strip().strip("\"'"))
    return environment


def job_status(slug: str) -> dict | None:
    """Return a project's job status (None if it never had one), with a log tail.

    A job recorded as running but with no live thread in this server (the server restarted)
    is reported as interrupted.
    """
    path = _status_path(slug)
    if not path.exists():
        return None
    status = json.loads(path.read_text())
    if status["state"] == "running" and slug not in _running:
        status["state"] = "interrupted"
    log_path = JOBS_DIR / f"{slug}.log"
    lines = log_path.read_text(errors="replace").splitlines() if log_path.exists() else []
    status["log_tail"] = "\n".join(lines[-30:])
    return status


def active_job() -> str | None:
    """Return the slug of the job running in this server, if any."""
    with _JOBS_LOCK:
        for slug, thread in list(_running.items()):
            if thread.is_alive():
                return slug
            del _running[slug]
    return None


def start_job(
    slug: str,
    stages: list[list[str]],
    script: str = "deep_dive.py",
) -> dict:
    """Start running `stages` for `slug` in a background thread.

    Args:
        slug: Job name (a project slug for deep dives); names the status and log files.
        stages: Argument lists for the script, run in order.
        script: File name in `scripts/`; `.sh` scripts run with zsh, others with this Python.

    Returns:
        The initial status.

    Raises:
        RuntimeError: If a job is already running.
    """
    with _JOBS_LOCK:
        for other, thread in _running.items():
            if thread.is_alive():
                raise RuntimeError(f"a deep-dive job is already running ({other})")
        status = {
            "slug": slug,
            "script": script,
            "stages": stages,
            "current": 0,
            "state": "running",
            "started": _now(),
            "finished": None,
            "error": None,
        }
        _write_status(slug, status)
        thread = threading.Thread(target=_run, args=(slug, status), daemon=True)
        _running[slug] = thread
        thread.start()
    return status


def resume_job(slug: str) -> dict:
    """Restart an interrupted or failed job from the stage it stopped on."""
    status = job_status(slug)
    if status is None or status["state"] not in ("interrupted", "failed"):
        raise RuntimeError("nothing to resume")
    return start_job(
        slug,
        status["stages"][status["current"] :],
        status.get("script", "deep_dive.py"),
    )


def _run(slug: str, status: dict) -> None:
    log_path = JOBS_DIR / f"{slug}.log"
    environment = _environment()
    script_path = SCRIPTS_DIR / status["script"]
    interpreter = ["/bin/zsh"] if script_path.suffix == ".sh" else [sys.executable]
    try:
        for index, stage in enumerate(status["stages"]):
            status["current"] = index
            _write_status(slug, status)
            with log_path.open("a") as log:
                log.write(f"\n=== {_now()} {status['script']} {' '.join(stage)}\n")
                log.flush()
                completed = subprocess.run(
                    [*interpreter, str(script_path), *stage],
                    cwd=CODE_ROOT,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            if completed.returncode != 0:
                status["state"] = "failed"
                label = stage[0] if stage else status["script"]
                status["error"] = f"stage '{label}' exited with {completed.returncode}"
                break
        else:
            status["state"] = "done"
    except OSError as error:
        status["state"] = "failed"
        status["error"] = str(error)
    status["finished"] = _now()
    _write_status(slug, status)
    with _JOBS_LOCK:
        _running.pop(slug, None)
