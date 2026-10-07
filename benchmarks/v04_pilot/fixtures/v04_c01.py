"""Pins v04_c01: 20 threads x 100 increments land exactly on 2000."""
from src.v04.c01.counter import AtomicCounter
from src.v04.c01.workers import run_workers

c = AtomicCounter()
run_workers(c, n_threads=20, n_incr=100)
assert c.value == 2000, c.value
print("EVAL_PASSED")
