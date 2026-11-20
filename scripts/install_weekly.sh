#!/bin/zsh
# Install (or reinstall) the weekly launchd job; pass --uninstall to remove it. macOS only.
#
# The job runs scripts/weekly.sh against $LITFEED_DATA as set when you run this installer
# (else data/ in this checkout). Edit the schedule in configs/launchd/ and rerun to apply.
# Check status:   launchctl print gui/$(id -u)/local.litfeed.weekly
# Run it now:     launchctl kickstart gui/$(id -u)/local.litfeed.weekly

set -eu
[[ "$(uname)" == Darwin ]] || { echo "weekly scheduling uses launchd and is macOS-only for now" >&2; exit 1; }
REPO="${0:A:h:h}"
DATA="${LITFEED_DATA:-$REPO/data}"
DATA="${DATA:A}"
LABEL="local.litfeed.weekly"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

# remove any loaded copy first so edits to the plist take effect
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$TARGET"
  echo "uninstalled $LABEL"
  exit 0
fi

[[ -d "$DATA" ]] || { echo "no data directory at $DATA (run scripts/init_data.py)" >&2; exit 1; }
mkdir -p "$DATA/logs" "$HOME/Library/LaunchAgents"
sed -e "s|__REPO__|$REPO|g" -e "s|__DATA__|$DATA|g" \
  "$REPO/configs/launchd/$LABEL.plist" >"$TARGET"
plutil -lint "$TARGET" >/dev/null
launchctl bootstrap "$DOMAIN" "$TARGET"
echo "installed $LABEL -> $TARGET (data: $DATA)"
