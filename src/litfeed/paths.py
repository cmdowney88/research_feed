"""Where the code and the user's data live.

The code checkout holds only the framework (package, scripts, prompts). Everything personal
(feed config, seeds, taste profile and ratings, triage results, digests, notes, projects, the
library, caches, logs, and the `.env` file with API keys) lives in a separate data directory:
`$LITFEED_DATA` if set, else `data/` inside the code checkout (gitignored there, so it can be
its own git repository). `python scripts/init_data.py` creates one from `examples/`.
"""

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("LITFEED_DATA") or CODE_ROOT / "data").expanduser().resolve()
PROMPTS_DIR = CODE_ROOT / "prompts"
