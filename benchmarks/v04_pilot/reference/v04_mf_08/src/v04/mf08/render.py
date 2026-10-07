"""CSV rendering."""
from __future__ import annotations

def to_csv(rows) -> str:
    if not rows:
        return ""
    header = list(rows[0].keys())
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(str(r[h]) for h in header))
    return "\n".join(lines) + "\n"
