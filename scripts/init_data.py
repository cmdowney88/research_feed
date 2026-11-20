"""Create a data directory from the templates in `examples/`.

The data directory holds everything personal (see `litfeed.paths`): `$LITFEED_DATA`, else
`data/` in the code checkout. Existing files are never overwritten.

Example:
    python scripts/init_data.py
    LITFEED_DATA=~/my_feed_data python scripts/init_data.py
"""

import shutil

from litfeed.paths import CODE_ROOT, DATA_ROOT

TEMPLATES = {
    "configs/feeds.yaml": "examples/feeds.yaml",
    "taste/profile.md": "examples/profile.md",
}
DIRECTORIES = ["seeds", "projects", "library", "notes", "triage", "digests"]
GITIGNORE = "cache/\nfetches/\nlogs/\nlibrary/pdfs/\n.env\n"
ENV_TEMPLATE = (
    "# API keys and settings for scripts run outside your shell (launchd, the UI's jobs).\n"
    "S2_API_KEY=\n"
    "ANTHROPIC_API_KEY=\n"
    "# the Python that has litfeed installed (for scripts/weekly.sh under launchd)\n"
    "LITFEED_PYTHON=\n"
)


def main() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    created = []
    for target, source in TEMPLATES.items():
        path = DATA_ROOT / target
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(CODE_ROOT / source, path)
            created.append(target)
    for directory in DIRECTORIES:
        (DATA_ROOT / directory).mkdir(exist_ok=True)
    for name, content in ((".gitignore", GITIGNORE), (".env", ENV_TEMPLATE)):
        path = DATA_ROOT / name
        if not path.exists():
            path.write_text(content)
            created.append(name)
    print(f"data directory: {DATA_ROOT}")
    for name in created:
        print(f"  created {name}")
    print("next: fill in .env, edit configs/feeds.yaml and taste/profile.md, then add seeds")
    print("(python scripts/serve_ui.py → /feeds, or seeds/<feed>.tsv by hand)")


if __name__ == "__main__":
    main()
