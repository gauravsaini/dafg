"""Shim for test_service.py inside generation folders, delegating to harness.test_service."""
from __future__ import annotations

import sys
from pathlib import Path

CURR_DIR = Path(__file__).resolve().parent
EVAL_DIR = CURR_DIR.parent.parent
if str(CURR_DIR) not in sys.path:
    sys.path.insert(0, str(CURR_DIR))
if str(EVAL_DIR) not in sys.path:
    sys.path.append(str(EVAL_DIR))

from harness.test_service import main

if __name__ == '__main__':
    main()
