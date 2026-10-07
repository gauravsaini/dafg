"""Pins v04_mf_02: env loading, type coercion, defaults, validation errors."""
from src.v04.mf02.config import Config, from_mapping
from src.v04.mf02.loader import load_from_env
from src.v04.mf02.validator import validate

c = load_from_env({"APP_HOST": "example.com", "APP_PORT": "9090", "APP_DEBUG": "true"})
assert (c.host, c.port, c.debug) == ("example.com", 9090, True), c
c2 = load_from_env({})
assert (c2.host, c2.port, c2.debug) == ("localhost", 8080, False), c2
assert validate(Config(host="", port=8080)) == ["host required"]
assert validate(Config(host="h", port=0)) == ["port out of range"]
assert validate(Config(host="h", port=70000)) == ["port out of range"]
assert validate(c) == []
print("EVAL_PASSED")
