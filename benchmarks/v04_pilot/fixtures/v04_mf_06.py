"""Pins v04_mf_06: stock reserve/release with OutOfStock, discount math."""
from src.v04.mf06.product import Product
from src.v04.mf06.inventory import Inventory, OutOfStock
from src.v04.mf06.pricing import discounted

inv = Inventory()
inv.add(Product("A", 1000, 10))
inv.reserve("A", 4)
assert inv.stock_of("A") == 6
try:
    inv.reserve("A", 7)
    raise AssertionError("expected OutOfStock")
except OutOfStock:
    pass
inv.release("A", 2)
assert inv.stock_of("A") == 8
assert discounted(1000, 25) == 750
assert discounted(1000, 0) == 1000
try:
    discounted(100, 150)
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("EVAL_PASSED")
