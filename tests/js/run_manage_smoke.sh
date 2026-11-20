#!/usr/bin/env bash
# Smoke-test the feeds page and the project page's deep-dive panels without a browser (macOS
# only: uses JXA). Page data comes from the real server code (the project page's pipeline state
# is faked for the checkpoint and running scenarios); each scenario in tests/js/scenarios/
# simulates clicks against tests/js/fake_dom.js and prints what it checked. Nothing is written:
# every API call is answered by the fake fetch.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
project="${1:-demo-project}"
# use the fixture data unless LITFEED_DATA points elsewhere
export LITFEED_DATA="${LITFEED_DATA:-$repo/tests/fixtures/data}"
python="${PYTHON:-python}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
"$python" - "$project" "$work" <<'PY'
import json, re, sys
from pathlib import Path
from litfeed.web.server import page, project_page
from litfeed.web.manage import feeds_page_data

def page_data(html: bytes) -> dict:
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', html.decode(), re.S)
    return json.loads(match.group(1).replace("<\\/", "</"))

project, work = sys.argv[1], Path(sys.argv[2])
(work / "feeds.json").write_text(json.dumps(feeds_page_data()))
data = page_data(project_page(project))
core = [paper for paper in data["papers"] if paper["relevance"] == "core"][:4]
related = [paper for paper in data["papers"] if paper["relevance"] == "related"][:2]
row = lambda paper: {"paperId": paper["paperId"], "year": paper.get("year"), "signals": 1,
                     "aspect": paper.get("aspect") or "", "title": paper["title"]}
data["pipeline"] = {"job": None, "awaitingSeeds": True, "proposed": [row(p) for p in core],
                    "related": [row(p) for p in related], "hasSynthesis": False}
(work / "checkpoint.json").write_text(json.dumps(data))
data["pipeline"] = {"job": {"state": "running", "current": 1, "error": None, "log_tail": "x",
                            "stages": [["recommend", project], ["notes", project],
                                       ["synthesize", project]]},
                    "awaitingSeeds": False, "proposed": [], "related": [], "hasSynthesis": True}
(work / "running.json").write_text(json.dumps(data))
PY
run() {
  local scenario="$1" script="$2"
  echo "--- $scenario"
  osascript -l JavaScript -e "
ObjC.import('Foundation');
function read(p){ return \$.NSString.stringWithContentsOfFileEncodingError(p, \$.NSUTF8StringEncoding, null).js; }
var PAGE_DATA = read('$work/$scenario.json'); var setTimeout = function(){};
eval(read('$repo/tests/js/fake_dom.js') + '\n' + read('$repo/src/litfeed/web/static/common.js') + '\n'
     + read('$repo/src/litfeed/web/static/$script') + '\n' + read('$repo/tests/js/scenarios/$scenario.js'));
''" 2>&1
}
run feeds feeds.js
run checkpoint project.js
run running project.js
