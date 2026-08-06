# conftest.py
"""Put the repo root on sys.path so tests can `from scripts.x import y`.

This repo has no packaging metadata and its only other test is a standalone
script, so there is nothing else establishing import paths.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
