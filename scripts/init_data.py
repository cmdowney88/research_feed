"""Create a data directory from the templates in `examples/`.

The data directory holds everything personal (see `litfeed.paths`): `$LITFEED_DATA`, else
`data/` in the code checkout. Existing files are never overwritten. `scripts/serve_ui.py` does
this automatically and then walks you through the rest at /setup.

Example:
    python scripts/init_data.py
    LITFEED_DATA=~/my_feed_data python scripts/init_data.py
"""

from litfeed.paths import DATA_ROOT
from litfeed.setup import init_data_dir


def main() -> None:
    created = init_data_dir()
    print(f"data directory: {DATA_ROOT}")
    for name in created:
        print(f"  created {name}")
    print("next: python scripts/serve_ui.py, then follow /setup")


if __name__ == "__main__":
    main()
