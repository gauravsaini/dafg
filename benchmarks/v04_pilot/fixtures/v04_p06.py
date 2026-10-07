"""Pins v04_p06: cursor pagination covers items exactly once; bad cursor rejected."""
from src.v04.p06.cursor import encode, decode, BadCursor
from src.v04.p06.page import paginate

items = list(range(10))
seen = []
cur = None
while True:
    page, cur = paginate(items, 3, cur)
    seen.extend(page)
    if cur is None:
        break
assert seen == items, seen
p1, c1 = paginate(items, 4)
assert p1 == [0, 1, 2, 3] and c1 is not None
p2, c2 = paginate(items, 4, c1)
assert p2 == [4, 5, 6, 7]
p3, c3 = paginate(items, 4, c2)
assert p3 == [8, 9] and c3 is None
try:
    decode("!!!not-a-cursor!!!")
    raise AssertionError("expected BadCursor")
except BadCursor:
    pass
print("EVAL_PASSED")
