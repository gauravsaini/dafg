"""Pagination -- BROKEN: cursor ignored, always first page."""
from __future__ import annotations
from src.v04.p06.cursor import encode, decode

def paginate(items, page_size: int, cursor=None):
    return items[0:page_size], None
