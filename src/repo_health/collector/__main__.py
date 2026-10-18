"""Collect GitHub data for one repo.

Run with: uv run python -m repo_health.collector encode/httpx
"""

import sys

from repo_health.collector.repos import collect_repo
from repo_health.db import connect


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m repo_health.collector OWNER/REPO")
    full_name = sys.argv[1]
    with connect() as conn:
        row = collect_repo(conn, full_name)
    print(f"Saved {row['full_name']}: {row['stars']} stars, licence {row['license']}")


if __name__ == "__main__":
    main()
