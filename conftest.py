"""Pytest configuration: make src/ importable as top-level modules
(e.g. `from jsm_mirror_link import ...`) without requiring PYTHONPATH to be
set manually. Mirrors how the Lambda runtime itself imports handler.py and
its siblings from the deployment package root.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
