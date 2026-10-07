"""Closeable channel."""
from __future__ import annotations
import queue

class ChannelClosed(Exception):
    pass

class Channel:
    def __init__(self):
        self._q = queue.Queue()
        self._closed = False
    def put(self, item) -> None:
        if self._closed:
            raise ChannelClosed("put on closed channel")
        self._q.put(item)
    def get(self):
        try:
            return self._q.get(timeout=5)
        except queue.Empty:
            raise ChannelClosed("get on drained channel")
    def close(self) -> None:
        self._closed = True
    def empty(self) -> bool:
        return self._q.empty()
