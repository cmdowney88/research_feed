"""Serve the local literature UI: digests (rate, save) and deep-dive projects (👍/👎, save).

The server binds to 127.0.0.1 only and uses the standard library; see `litfeed.web.server`
for the pages and API.

Example:
    python scripts/serve_ui.py            # then open http://127.0.0.1:8765
"""

import argparse
import webbrowser
from http.server import ThreadingHTTPServer

from litfeed.web.server import UIHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), UIHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"serving literature UI at {url} (Ctrl-C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
