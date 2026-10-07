"""Pins v04_mf_03: money arithmetic with currency checks, ledger balances, trial balance."""
from src.v04.mf03.money import Money, CurrencyMismatch
from src.v04.mf03.ledger import Ledger
from src.v04.mf03.report import trial_balance

assert (Money(100, "USD") + Money(50, "USD")).cents == 150
assert (Money(100, "USD") - Money(30, "USD")).cents == 70
try:
    Money(100, "USD") + Money(50, "EUR")
    raise AssertionError("expected CurrencyMismatch")
except CurrencyMismatch:
    pass
led = Ledger()
led.post("cash", Money(10000, "USD"))
led.post("cash", Money(-2500, "USD"))
led.post("rev", Money(2500, "USD"))
assert led.balance("cash", "USD").cents == 7500
assert led.balance("nobody", "USD").cents == 0
tb = trial_balance(led, "USD")
assert tb == {"cash": 7500, "rev": 2500}, tb
print("EVAL_PASSED")
