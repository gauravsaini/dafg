#!/usr/bin/env python3
"""Programmatically compare experiment directories from raw artifacts."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dafg.compare import ExperimentComparator

def main():
    args = sys.argv[1:]
    if not args or "-h" in args or "--help" in args:
        print("Usage: uv run python scripts/compare_experiments.py <experiment_dir1> [dir2...] [--json]")
        sys.exit(0)

    as_json = "--json" in args
    as_fresh = "--fresh" in args
    paths = [Path(p) for p in args if p not in ("--json", "--fresh")]

    records = [ExperimentComparator.analyze_dir(p, fresh=as_fresh) for p in paths]
    if as_json:
        import json
        print(json.dumps([r.to_dict() for r in records], indent=2))
    else:
        print(ExperimentComparator.generate_markdown_table(records))

if __name__ == "__main__":
    main()
