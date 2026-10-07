"""Pins v04_c04: barrier synchronizes 5 threads across 2 rounds; gather preserves order."""
import threading
from src.v04.c04.barrier import Barrier
from src.v04.c04.collect import gather

b = Barrier(5)
passed = []
lock = threading.Lock()
def worker(i):
    for _ in range(2):
        b.wait()
    with lock:
        passed.append(i)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=5)
assert not any(t.is_alive() for t in threads), "barrier deadlock"
assert sorted(passed) == [0, 1, 2, 3, 4]
assert gather([lambda: 1, lambda: 2, lambda: 3]) == [1, 2, 3]
print("EVAL_PASSED")
