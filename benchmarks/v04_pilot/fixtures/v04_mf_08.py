"""Pins v04_mf_08: CSV parse, group-sum aggregation, render round-trip."""
from src.v04.mf08.parse import parse_rows
from src.v04.mf08.aggregate import sum_by_key
from src.v04.mf08.render import to_csv

rows = parse_rows("name,amt\na,10\na,20\nb,5\n")
assert rows == [{"name": "a", "amt": "10"}, {"name": "a", "amt": "20"}, {"name": "b", "amt": "5"}], rows
assert sum_by_key(rows, "name", "amt") == {"a": 30, "b": 5}
rt = parse_rows(to_csv(rows))
assert rt == rows, rt
print("EVAL_PASSED")
