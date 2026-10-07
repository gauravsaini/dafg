"""Schema validation with dotted error paths."""
from __future__ import annotations

def validate(payload: dict, schema: dict, _path: str = ""):
    errors = []
    for key, expected in schema.items():
        path = f"{_path}.{key}" if _path else key
        if key not in payload:
            errors.append(f"missing: {path}")
            continue
        val = payload[key]
        if isinstance(expected, dict):
            if not isinstance(val, dict):
                errors.append(f"{path}: expected object, got {type(val).__name__}")
            else:
                errors.extend(validate(val, expected, path))
        elif not isinstance(val, expected):
            errors.append(f"{path}: expected {expected.__name__}, got {type(val).__name__}")
    return errors
