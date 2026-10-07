"""Pins v04_c02: 100 items through 4 consumers exactly once; close semantics."""
from src.v04.c02.channel import Channel, ChannelClosed
from src.v04.c02.pipeline import run_pipeline

out = run_pipeline(list(range(100)), n_consumers=4)
assert sorted(out) == list(range(100)), len(out)
ch = Channel()
ch.put("x")
ch.close()
assert ch.get() == "x"
try:
    ch.put("y")
    raise AssertionError("expected ChannelClosed")
except ChannelClosed:
    pass
print("EVAL_PASSED")
