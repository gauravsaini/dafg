"""Pins v04_mf_04: todo add/complete, overdue filter with explicit now, completion rate."""
from src.v04.mf04.store import TodoStore
from src.v04.mf04.filters import overdue
from src.v04.mf04.stats import completion_rate

s = TodoStore()
a = s.add("past1", due_ts=900.0)
b = s.add("past2", due_ts=950.0)
c = s.add("future", due_ts=1100.0)
s.complete(a)
assert len(s.list_open()) == 2
od = overdue(s.all(), now_ts=1000.0)
assert [t.id for t in od] == [b], [t.id for t in od]
assert abs(completion_rate(s.all()) - 1/3) < 1e-9
assert completion_rate([]) == 0.0
print("EVAL_PASSED")
