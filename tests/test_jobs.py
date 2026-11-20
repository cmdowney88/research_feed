import json
import time
from pathlib import Path

import pytest

from litfeed import jobs


@pytest.fixture
def fake_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "deep_dive.py"
    script.write_text(
        "import sys\n"
        "print('stage', sys.argv[1])\n"
        "sys.exit(3 if sys.argv[1] == 'fail' else 0)\n"
    )
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "ENV_PATH", tmp_path / "missing.env")
    return tmp_path


def wait_for(slug: str) -> dict:
    for _ in range(100):
        if jobs.active_job() is None:
            return jobs.job_status(slug)
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_runs_stages_in_order(fake_jobs: Path) -> None:
    jobs.start_job("demo", [["one", "demo"], ["two", "demo"]])
    status = wait_for("demo")
    assert status["state"] == "done"
    assert "stage one" in status["log_tail"] and "stage two" in status["log_tail"]


def test_failed_stage_stops_and_resumes_from_it(fake_jobs: Path) -> None:
    jobs.start_job("demo", [["one", "demo"], ["fail", "demo"], ["three", "demo"]])
    status = wait_for("demo")
    assert status["state"] == "failed"
    assert status["current"] == 1
    assert "stage three" not in status["log_tail"]
    with pytest.raises(RuntimeError):
        jobs.resume_job("never-started")
    jobs.resume_job("demo")
    status = wait_for("demo")
    # resuming reruns the failing stage first
    assert status["stages"][0][0] == "fail"
    assert status["state"] == "failed"


def test_running_without_thread_is_interrupted(fake_jobs: Path) -> None:
    (fake_jobs / "jobs").mkdir()
    status = {"slug": "demo", "stages": [["one"]], "current": 0, "state": "running",
              "started": "", "finished": None, "error": None}
    (fake_jobs / "jobs" / "demo.json").write_text(json.dumps(status))
    assert jobs.job_status("demo")["state"] == "interrupted"
