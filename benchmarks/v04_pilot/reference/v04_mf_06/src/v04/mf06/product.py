"""Product value object."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Product:
    sku: str
    price_cents: int
    stock: int
    def __post_init__(self):
        if self.price_cents < 0:
            raise ValueError("price_cents must be >= 0")
        if self.stock < 0:
            raise ValueError("stock must be >= 0")
