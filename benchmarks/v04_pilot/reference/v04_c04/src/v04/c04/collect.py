"""Threaded gather preserving order."""
from __future__ import annotations
import threading

def gather(fns):
    results = [None] * len(fns)
    def run(i, fn):
        results[i] = fn()
    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results
