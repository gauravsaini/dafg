"""Pins v04_mf_01: user create/get/deactivate flow across models/services/controller."""
from src.v04.mf01.models import User, validate_username
from src.v04.mf01.services import UserService
from src.v04.mf01.controller import handle_create

svc = UserService()
code, body = handle_create(svc, {"username": "alice"})
assert code == 201 and body["username"] == "alice", (code, body)
u = svc.get(body["id"])
assert u.username == "alice" and u.active is True
svc.deactivate(u.id)
assert svc.get(u.id).active is False
try:
    svc.get(9999)
    raise AssertionError("expected KeyError")
except KeyError:
    pass
code, body = handle_create(svc, {"username": ""})
assert code == 400, (code, body)
code, body = handle_create(svc, {})
assert code == 422, (code, body)
try:
    validate_username("bad name!")
    raise AssertionError("expected ValueError")
except ValueError:
    pass
print("EVAL_PASSED")
