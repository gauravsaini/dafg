"""Thread workers driving a shared counter."""
from __future__ import annotations
import threading

def run_workers(counter, n_threads: int, n_incr: int) -> None:
    def work():
        for _ in range(n_incr):
            counter.incr()
    threads = [threading.Thread(target=work) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
