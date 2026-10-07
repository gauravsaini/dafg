"""Pipeline -- BROKEN: drops every 10th item."""
from __future__ import annotations
import threading
from src.v04.c02.channel import Channel

_SENTINEL = object()

def run_pipeline(items, n_consumers: int):
    ch = Channel()
    out = []
    lock = threading.Lock()
    def consumer():
        while True:
            item = ch.get()
            if item is _SENTINEL:
                return
            with lock:
                out.append(item)
    cons = [threading.Thread(target=consumer) for _ in range(n_consumers)]
    for t in cons:
        t.start()
    for i, it in enumerate(items):
        if i % 10 == 9:
            continue
        ch.put(it)
    for _ in range(n_consumers):
        ch.put(_SENTINEL)
    for t in cons:
        t.join()
    return out
