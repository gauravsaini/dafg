"""Pins v04_c06: 10 readers + 1 writer x 50 writes; no lost updates."""
import threading
from src.v04.c06.rwlock import RWLock
from src.v04.c06.store import SharedStore

s = SharedStore()
def writer():
    for i in range(1, 51):
        s.write("k", i)
def reader():
    for _ in range(200):
        s.read("k")
threads = [threading.Thread(target=writer)]
threads += [threading.Thread(target=reader) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=10)
assert not any(t.is_alive() for t in threads), "deadlock"
assert s.read("k") == 50, s.read("k")
print("EVAL_PASSED")
