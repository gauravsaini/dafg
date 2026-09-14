"""Root entry point for test_service.py, delegating directly to harness.test_service."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure harness is importable
CURR_DIR = Path(__file__).resolve().parent
if str(CURR_DIR) not in sys.path:
    sys.path.insert(0, str(CURR_DIR))

from harness.test_service import main

if __name__ == "__main__":
    main()
