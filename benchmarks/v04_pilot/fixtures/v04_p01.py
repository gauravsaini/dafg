"""Pins v04_p01: nested schema validation with dotted error paths."""
from src.v04.p01.schema import validate
from src.v04.p01.errors import format_errors

schema = {"name": str, "age": int, "addr": {"city": str}}
assert validate({"name": "a", "age": 3, "addr": {"city": "x"}}, schema) == []
assert validate({"age": 3, "addr": {"city": "x"}}, schema) == ["missing: name"]
assert validate({"name": "a", "age": "3", "addr": {"city": "x"}}, schema) == ["age: expected int, got str"]
assert validate({"name": "a", "age": 3, "addr": {"city": 9}}, schema) == ["addr.city: expected str, got int"]
errs = validate({"age": "x"}, schema)
assert format_errors(errs) == "missing: name; age: expected int, got str; missing: addr", format_errors(errs)
print("EVAL_PASSED")
