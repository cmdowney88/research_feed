"""Serve the local literature UI: setup, digests (rate, save), feeds and seeds, and deep dives.

The server binds to 127.0.0.1 only and uses the standard library; see `litfeed.web.server`
for the pages and API. On start it creates the data directory if needed (see
`litfeed.paths`), loads API keys from its `.env`, and opens /setup until setup is complete.

Example:
    python scripts/serve_ui.py            # then open http://127.0.0.1:8765
"""

import argparse
import webbrowser
from http.server import ThreadingHTTPServer

from litfeed.paths import DATA_ROOT
from litfeed.setup import init_data_dir, load_env_into_process, setup_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    created = init_data_dir()
    if created:
        print(f"created data directory {DATA_ROOT} ({', '.join(created)})")
    # load keys before the web modules build their API clients
    load_env_into_process()
    from litfeed.web.server import UIHandler

    server = ThreadingHTTPServer(("127.0.0.1", args.port), UIHandler)
    url = f"http://127.0.0.1:{args.port}"
    start_path = "/" if setup_status()["ready"] else "/setup"
    print(f"serving literature UI at {url} (data: {DATA_ROOT}; Ctrl-C to stop)")
    if not args.no_browser:
        webbrowser.open(url + start_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
