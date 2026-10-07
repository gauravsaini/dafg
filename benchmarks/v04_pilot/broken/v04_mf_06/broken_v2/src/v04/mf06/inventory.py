"""Inventory -- BROKEN: reserve skips the stock check."""
from __future__ import annotations

class OutOfStock(Exception):
    pass

class Inventory:
    def __init__(self):
        self._products = {}
    def add(self, product) -> None:
        self._products[product.sku] = product
    def stock_of(self, sku: str) -> int:
        return self._products[sku].stock
    def reserve(self, sku: str, qty: int) -> None:
        self._products[sku].stock -= qty
    def release(self, sku: str, qty: int) -> None:
        self._products[sku].stock += qty
