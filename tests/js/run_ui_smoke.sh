#!/usr/bin/env bash
# Smoke-test the project page script without a browser (macOS only: uses JXA).
# Renders real page data via litfeed.web.server, runs common.js + project.js against
# tests/js/fake_dom.js, clicks 👍 with the auto-save toggle on/off, and prints the API calls.
# Promises only settle after the JXA script finishes, so results are printed via console.log.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
project="${1:-demo-project}"
# use the fixture data unless LITFEED_DATA points elsewhere
export LITFEED_DATA="${LITFEED_DATA:-$repo/tests/fixtures/data}"
python="${PYTHON:-python}"
data_file="$(mktemp)"
trap 'rm -f "$data_file"' EXIT
"$python" -c "
import re, sys
from litfeed.web.server import project_page
page = project_page(sys.argv[1]).decode()
print(re.search(r'<script type=\"application/json\" id=\"data\">(.*?)</script>', page, re.S).group(1))
" "$project" > "$data_file"
osascript -l JavaScript -e "
ObjC.import('Foundation');
function read(p){ return \$.NSString.stringWithContentsOfFileEncodingError(p, \$.NSUTF8StringEncoding, null).js; }
var PAGE_DATA = read('$data_file'); var setTimeout = function(){};
eval(read('$repo/tests/js/fake_dom.js') + '\n' + read('$repo/src/litfeed/web/static/common.js') + '\n'
     + read('$repo/src/litfeed/web/static/project.js') + '\n' + \`
console.log('toggle default (storage blocked): ' + nodes.autosave.checked);
var buttons = [];
(function collect(n) { if (!(n instanceof FakeNode)) return;
  if (n.tagName === 'BUTTON' && n.className === 'thumb up') buttons.push(n); n.children.forEach(collect); })(nodes.papers);
buttons[0].listeners.click()
  .then(() => { console.log('toggle on  -> ' + JSON.stringify(calls)); calls.length = 0;
                nodes.autosave.checked = false; return buttons[1].listeners.click(); })
  .then(() => { console.log('toggle off -> ' + JSON.stringify(calls)); calls.length = 0;
                nodes.autosave.checked = true; data.library[data.papers[2].paperId] = {key: 'x', collection: 'c', pdf: ''};
                return buttons[2].listeners.click(); })
  .then(() => console.log('on, already saved -> ' + JSON.stringify(calls)), error => console.log('ERROR ' + error));
\`);
''" 2>&1
