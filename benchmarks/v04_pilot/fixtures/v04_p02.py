"""Pins v04_p02: FSM transitions and illegal-transition rejection."""
from src.v04.p02.states import INIT, READY, RUNNING, TERMINATED
from src.v04.p02.fsm import FSM, IllegalTransition

fsm = FSM({(INIT, "boot"): READY, (READY, "start"): RUNNING, (RUNNING, "stop"): TERMINATED}, INIT)
assert fsm.trigger("boot") == READY
assert fsm.trigger("start") == RUNNING
assert fsm.trigger("stop") == TERMINATED
assert fsm.state == TERMINATED
try:
    fsm.trigger("boot")
    raise AssertionError("expected IllegalTransition")
except IllegalTransition:
    pass
print("EVAL_PASSED")
