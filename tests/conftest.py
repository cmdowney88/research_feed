"""Point every test at the fixture data directory, never at the user's real data.

`litfeed.paths` reads `LITFEED_DATA` at import time, so this must run before any test module
imports litfeed (pytest loads conftest.py first).
"""

import os
from pathlib import Path

FIXTURE_DATA = Path(__file__).resolve().parent / "fixtures" / "data"
os.environ["LITFEED_DATA"] = str(FIXTURE_DATA)
