"""Pagination."""
from __future__ import annotations
from src.v04.p06.cursor import encode, decode

def paginate(items, page_size: int, cursor=None):
    offset = decode(cursor) if cursor else 0
    page = items[offset:offset + page_size]
    nxt = offset + page_size
    next_cursor = encode(nxt) if nxt < len(items) else None
    return page, next_cursor
