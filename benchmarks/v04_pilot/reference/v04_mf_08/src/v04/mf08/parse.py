"""Minimal CSV parsing (header + rows)."""
from __future__ import annotations

def parse_rows(text: str):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    header = [h.strip() for h in lines[0].split(",")]
    rows = []
    for ln in lines[1:]:
        vals = [v.strip() for v in ln.split(",")]
        rows.append(dict(zip(header, vals)))
    return rows
