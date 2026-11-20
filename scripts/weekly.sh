#!/bin/zsh
# Weekly literature run: fetch -> triage -> tier-1 notes -> digest, then a macOS notification.
#
# Run by launchd (see configs/launchd/ and scripts/install_weekly.sh) or by hand. The data
# directory is $LITFEED_DATA, else data/ in this checkout. launchd does not read ~/.zshrc, so
# put S2_API_KEY, ANTHROPIC_API_KEY, and LITFEED_PYTHON (the Python with litfeed installed)
# in <data>/.env. Output goes to <data>/logs/weekly-<date>.log.

set -u
setopt pipefail

REPO="${0:A:h:h}"
DATA="${LITFEED_DATA:-$REPO/data}"
MAX_NOTES=10
TODAY=$(date +%Y-%m-%d)
LOG="$DATA/logs/weekly-$TODAY.log"

# let `claude` (installed in ~/.local/bin) be found under launchd's minimal PATH
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"Literature\" sound name \"Glass\""
}

fail() {
  echo "FAILED: $1" >>"$LOG"
  notify "Weekly run failed: $1 (see logs/weekly-$TODAY.log)"
  exit 1
}

[[ -d "$DATA" ]] || { notify "Weekly run failed: no data directory at $DATA"; exit 1; }
mkdir -p "$DATA/logs"
echo "=== weekly run $(date) ===" >>"$LOG"

# load KEY=VALUE lines from .env without echoing them
if [[ -f "$DATA/.env" ]]; then
  set -a
  source "$DATA/.env"
  set +a
fi
export LITFEED_DATA="$DATA"
PYTHON="${LITFEED_PYTHON:-python3}"
[[ -n "${S2_API_KEY:-}" ]] || fail "S2_API_KEY not set in .env"
[[ -n "${ANTHROPIC_API_KEY:-}" ]] || fail "ANTHROPIC_API_KEY not set in .env"
"$PYTHON" -c "import litfeed" 2>/dev/null || fail "$PYTHON cannot import litfeed (set LITFEED_PYTHON)"

# skip if today's digest already exists (e.g. a manual run earlier today)
if [[ -f "$DATA/triage/$TODAY.jsonl" ]]; then
  echo "triage/$TODAY.jsonl exists; nothing to do" >>"$LOG"
  exit 0
fi

cd "$REPO" || fail "cannot cd to $REPO"

echo "--- fetch" >>"$LOG"
"$PYTHON" scripts/fetch_recommendations.py >>"$LOG" 2>&1 || fail "fetch"

echo "--- triage" >>"$LOG"
"$PYTHON" scripts/triage.py "$DATA/fetches/$TODAY.jsonl" >>"$LOG" 2>&1 || fail "triage"

echo "--- summarize" >>"$LOG"
"$PYTHON" scripts/summarize.py "$DATA/triage/$TODAY.jsonl" --max-tier 1 \
  --max-papers "$MAX_NOTES" >>"$LOG" 2>&1 || fail "summaries"

echo "--- digest" >>"$LOG"
"$PYTHON" scripts/render_digest.py "$DATA/triage/$TODAY.jsonl" >>"$LOG" 2>&1 || fail "digest"

counts=$("$PYTHON" -c '
import json, sys
tiers = [json.loads(line)["tier"] for line in open(sys.argv[1])]
print(", ".join(f"{tiers.count(tier)} tier-{tier}" for tier in (1, 2, 3)))
' "$DATA/triage/$TODAY.jsonl")
warning=""
grep -q "WARNING" "$LOG" && warning=" (warnings in log)"
echo "done: $counts$warning" >>"$LOG"
notify "Digest ready: $counts$warning. Open with scripts/serve_ui.py"
