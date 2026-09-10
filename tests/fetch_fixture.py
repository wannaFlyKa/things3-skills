#!/usr/bin/env python3
"""Download things.py's own test database into tests/fixtures/ if it is missing.

The URL comes from tests/fixtures/SOURCE.txt (the v1.0.1 tag). Nothing is downloaded when the
file already exists; the fixture is committed so the suite works offline.
"""

import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(HERE, "fixtures")
TARGET = os.path.join(FIXTURE_DIR, "main.sqlite")
SOURCE = os.path.join(FIXTURE_DIR, "SOURCE.txt")


def fixture_url() -> str:
    with open(SOURCE, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("https://"):
                return line
    raise SystemExit(f"no https:// URL found in {SOURCE}")


def main() -> int:
    if os.path.isfile(TARGET):
        print(f"fixture present: {TARGET}")
        return 0
    url = fixture_url()
    print(f"downloading {url}")
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    with open(TARGET, "wb") as handle:
        handle.write(data)
    print(f"wrote {len(data)} bytes to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
