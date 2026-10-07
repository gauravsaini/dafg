#!/usr/bin/env python3
"""Build the v04 fixture-redesign pilot suite.

Generates:
  benchmarks/v04_pilot/tasks.json            - task definitions (fixture_file refs)
  benchmarks/v04_pilot/fixtures/<id>.py      - behavior-pinning fixtures
  benchmarks/v04_pilot/reference/<id>/...    - correct reference implementations
  benchmarks/v04_pilot/broken/<id>/v1|v2/... - broken overlays for the validation gate

Conventions: owns paths live under src/v04/<task>/; fixtures import them as
absolute imports (namespace packages, no __init__ needed); every fixture ends
with print("EVAL_PASSED"); hermetic (no network, no wall clock); <5s each.
"""
import json
import os

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
HERE = os.path.normpath(HERE)

TASKS = []


def T(task_id, title, cohort, nodes, fixture, ref, broken_v1, broken_v2):
    TASKS.append({
        "task_id": task_id, "title": title, "cohort": cohort,
        "nodes": nodes, "fixture": fixture, "ref": ref,
        "broken_v1": broken_v1, "broken_v2": broken_v2,
    })


# =====================================================================
# MF-01: user flow (models / services / controller)
# =====================================================================
T(
    "v04_mf_01", "V04 User Create/Get/Deactivate Flow", "multifile",
    [
        ("v04_mf_01_models", "User Models", ["src/v04/mf01/models.py"], []),
        ("v04_mf_01_services", "User Services", ["src/v04/mf01/services.py"], ["v04_mf_01_models"]),
        ("v04_mf_01_ctrl", "User Controller", ["src/v04/mf01/controller.py"], ["v04_mf_01_services"]),
    ],
    '''"""Pins v04_mf_01: user create/get/deactivate flow across models/services/controller."""\nfrom src.v04.mf01.models import User, validate_username\nfrom src.v04.mf01.services import UserService\nfrom src.v04.mf01.controller import handle_create\n\nsvc = UserService()\ncode, body = handle_create(svc, {"username": "alice"})\nassert code == 201 and body["username"] == "alice", (code, body)\nu = svc.get(body["id"])\nassert u.username == "alice" and u.active is True\nsvc.deactivate(u.id)\nassert svc.get(u.id).active is False\ntry:\n    svc.get(9999)\n    raise AssertionError("expected KeyError")\nexcept KeyError:\n    pass\ncode, body = handle_create(svc, {"username": ""})\nassert code == 400, (code, body)\ncode, body = handle_create(svc, {})\nassert code == 422, (code, body)\ntry:\n    validate_username("bad name!")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf01/models.py": '''"""User domain model."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\n@dataclass\nclass User:\n    id: int\n    username: str\n    active: bool = True\n\ndef validate_username(name: str) -> str:\n    if not name or len(name) > 32 or not all(c.isalnum() or c == "_" for c in name):\n        raise ValueError(f"invalid username: {name!r}")\n    return name\n''',
        "src/v04/mf01/services.py": '''"""User service layer."""\nfrom __future__ import annotations\nfrom src.v04.mf01.models import User, validate_username\n\nclass UserService:\n    def __init__(self) -> None:\n        self._users = {}\n        self._next_id = 1\n    def create(self, username: str) -> User:\n        validate_username(username)\n        user = User(id=self._next_id, username=username)\n        self._users[user.id] = user\n        self._next_id += 1\n        return user\n    def get(self, uid: int) -> User:\n        return self._users[uid]\n    def deactivate(self, uid: int) -> None:\n        self._users[uid].active = False\n''',
        "src/v04/mf01/controller.py": '''"""HTTP-ish controller (no framework)."""\nfrom __future__ import annotations\nfrom src.v04.mf01.services import UserService\n\ndef handle_create(service: UserService, payload: dict):\n    if "username" not in payload:\n        return 422, {"error": "username required"}\n    try:\n        user = service.create(payload["username"])\n    except ValueError as exc:\n        return 400, {"error": str(exc)}\n    return 201, {"id": user.id, "username": user.username}\n''',
    },
    {"src/v04/mf01/models.py": "def broken(:\n"},
    {"src/v04/mf01/controller.py": '''"""HTTP-ish controller (no framework) -- BROKEN: swallows validation, wrong status."""\nfrom __future__ import annotations\nfrom src.v04.mf01.services import UserService\n\ndef handle_create(service: UserService, payload: dict):\n    if "username" not in payload:\n        return 422, {"error": "username required"}\n    try:\n        user = service.create(payload["username"])\n    except ValueError:\n        user = service.create("fallback")\n    return 200, {"id": user.id, "username": user.username}\n'''},
)

# =====================================================================
# MF-02: config loader (config / loader / validator)
# =====================================================================
T(
    "v04_mf_02", "V04 Config Load/Coerce/Validate", "multifile",
    [
        ("v04_mf_02_config", "Config Value Object", ["src/v04/mf02/config.py"], []),
        ("v04_mf_02_loader", "Env Loader", ["src/v04/mf02/loader.py"], ["v04_mf_02_config"]),
        ("v04_mf_02_validator", "Config Validator", ["src/v04/mf02/validator.py"], ["v04_mf_02_config"]),
    ],
    '''"""Pins v04_mf_02: env loading, type coercion, defaults, validation errors."""\nfrom src.v04.mf02.config import Config, from_mapping\nfrom src.v04.mf02.loader import load_from_env\nfrom src.v04.mf02.validator import validate\n\nc = load_from_env({"APP_HOST": "example.com", "APP_PORT": "9090", "APP_DEBUG": "true"})\nassert (c.host, c.port, c.debug) == ("example.com", 9090, True), c\nc2 = load_from_env({})\nassert (c2.host, c2.port, c2.debug) == ("localhost", 8080, False), c2\nassert validate(Config(host="", port=8080)) == ["host required"]\nassert validate(Config(host="h", port=0)) == ["port out of range"]\nassert validate(Config(host="h", port=70000)) == ["port out of range"]\nassert validate(c) == []\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf02/config.py": '''"""Config value object with coercion."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\nTRUE_STRINGS = {"true", "1", "yes", "on"}\n\n@dataclass\nclass Config:\n    host: str = "localhost"\n    port: int = 8080\n    debug: bool = False\n\ndef _to_bool(v) -> bool:\n    if isinstance(v, bool):\n        return v\n    return str(v).strip().lower() in TRUE_STRINGS\n\ndef from_mapping(m: dict) -> Config:\n    return Config(\n        host=m.get("host", "localhost"),\n        port=int(m.get("port", 8080)),\n        debug=_to_bool(m.get("debug", False)),\n    )\n''',
        "src/v04/mf02/loader.py": '''"""Load config from env-style mapping."""\nfrom __future__ import annotations\nfrom src.v04.mf02.config import from_mapping, Config\n\ndef load_from_env(env: dict) -> Config:\n    mapping = {}\n    if "APP_HOST" in env:\n        mapping["host"] = env["APP_HOST"]\n    if "APP_PORT" in env:\n        mapping["port"] = env["APP_PORT"]\n    if "APP_DEBUG" in env:\n        mapping["debug"] = env["APP_DEBUG"]\n    return from_mapping(mapping)\n''',
        "src/v04/mf02/validator.py": '''"""Config validation."""\nfrom __future__ import annotations\nfrom src.v04.mf02.config import Config\n\ndef validate(cfg: Config):\n    errors = []\n    if not cfg.host:\n        errors.append("host required")\n    if not (1 <= cfg.port <= 65535):\n        errors.append("port out of range")\n    return errors\n''',
    },
    {"src/v04/mf02/config.py": "def broken(:\n"},
    {"src/v04/mf02/validator.py": '''"""Config validation -- BROKEN: never reports errors."""\nfrom __future__ import annotations\nfrom src.v04.mf02.config import Config\n\ndef validate(cfg: Config):\n    return []\n'''},
)

# =====================================================================
# MF-03: money / ledger / trial balance
# =====================================================================
T(
    "v04_mf_03", "V04 Money Arithmetic and Trial Balance", "multifile",
    [
        ("v04_mf_03_money", "Money Value Object", ["src/v04/mf03/money.py"], []),
        ("v04_mf_03_ledger", "Ledger", ["src/v04/mf03/ledger.py"], ["v04_mf_03_money"]),
        ("v04_mf_03_report", "Trial Balance", ["src/v04/mf03/report.py"], ["v04_mf_03_ledger"]),
    ],
    '''"""Pins v04_mf_03: money arithmetic with currency checks, ledger balances, trial balance."""\nfrom src.v04.mf03.money import Money, CurrencyMismatch\nfrom src.v04.mf03.ledger import Ledger\nfrom src.v04.mf03.report import trial_balance\n\nassert (Money(100, "USD") + Money(50, "USD")).cents == 150\nassert (Money(100, "USD") - Money(30, "USD")).cents == 70\ntry:\n    Money(100, "USD") + Money(50, "EUR")\n    raise AssertionError("expected CurrencyMismatch")\nexcept CurrencyMismatch:\n    pass\nled = Ledger()\nled.post("cash", Money(10000, "USD"))\nled.post("cash", Money(-2500, "USD"))\nled.post("rev", Money(2500, "USD"))\nassert led.balance("cash", "USD").cents == 7500\nassert led.balance("nobody", "USD").cents == 0\ntb = trial_balance(led, "USD")\nassert tb == {"cash": 7500, "rev": 2500}, tb\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf03/money.py": '''"""Money value object."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\nclass CurrencyMismatch(Exception):\n    pass\n\n@dataclass(frozen=True)\nclass Money:\n    cents: int\n    currency: str\n    def _check(self, other):\n        if self.currency != other.currency:\n            raise CurrencyMismatch(f"{self.currency} != {other.currency}")\n    def __add__(self, other):\n        self._check(other)\n        return Money(self.cents + other.cents, self.currency)\n    def __sub__(self, other):\n        self._check(other)\n        return Money(self.cents - other.cents, self.currency)\n''',
        "src/v04/mf03/ledger.py": '''"""Simple ledger."""\nfrom __future__ import annotations\nfrom src.v04.mf03.money import Money\n\nclass Ledger:\n    def __init__(self):\n        self._entries = []\n    def post(self, account: str, money: Money) -> None:\n        self._entries.append((account, money))\n    def entries(self):\n        return list(self._entries)\n    def balance(self, account: str, currency: str) -> Money:\n        total = 0\n        for acct, m in self._entries:\n            if acct == account and m.currency == currency:\n                total += m.cents\n        return Money(total, currency)\n''',
        "src/v04/mf03/report.py": '''"""Trial balance report."""\nfrom __future__ import annotations\n\ndef trial_balance(ledger, currency: str):\n    totals = {}\n    for acct, m in ledger.entries():\n        if m.currency == currency:\n            totals[acct] = totals.get(acct, 0) + m.cents\n    return totals\n''',
    },
    {"src/v04/mf03/money.py": "def broken(:\n"},
    {"src/v04/mf03/money.py": '''"""Money value object -- BROKEN: __add__ ignores currency."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\nclass CurrencyMismatch(Exception):\n    pass\n\n@dataclass(frozen=True)\nclass Money:\n    cents: int\n    currency: str\n    def _check(self, other):\n        if self.currency != other.currency:\n            raise CurrencyMismatch(f"{self.currency} != {other.currency}")\n    def __add__(self, other):\n        return Money(self.cents + other.cents, self.currency)\n    def __sub__(self, other):\n        self._check(other)\n        return Money(self.cents - other.cents, self.currency)\n'''},
)

# =====================================================================
# MF-04: todo store / filters / stats
# =====================================================================
T(
    "v04_mf_04", "V04 Todo Store, Overdue Filter, Stats", "multifile",
    [
        ("v04_mf_04_store", "Todo Store", ["src/v04/mf04/store.py"], []),
        ("v04_mf_04_filters", "Todo Filters", ["src/v04/mf04/filters.py"], ["v04_mf_04_store"]),
        ("v04_mf_04_stats", "Todo Stats", ["src/v04/mf04/stats.py"], ["v04_mf_04_store"]),
    ],
    '''"""Pins v04_mf_04: todo add/complete, overdue filter with explicit now, completion rate."""\nfrom src.v04.mf04.store import TodoStore\nfrom src.v04.mf04.filters import overdue\nfrom src.v04.mf04.stats import completion_rate\n\ns = TodoStore()\na = s.add("past1", due_ts=900.0)\nb = s.add("past2", due_ts=950.0)\nc = s.add("future", due_ts=1100.0)\ns.complete(a)\nassert len(s.list_open()) == 2\nod = overdue(s.all(), now_ts=1000.0)\nassert [t.id for t in od] == [b], [t.id for t in od]\nassert abs(completion_rate(s.all()) - 1/3) < 1e-9\nassert completion_rate([]) == 0.0\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf04/store.py": '''"""Todo store."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\n@dataclass\nclass Todo:\n    id: int\n    title: str\n    due_ts: float\n    completed: bool = False\n\nclass TodoStore:\n    def __init__(self):\n        self._todos = {}\n        self._next = 1\n    def add(self, title: str, due_ts: float) -> int:\n        tid = self._next\n        self._todos[tid] = Todo(id=tid, title=title, due_ts=due_ts)\n        self._next += 1\n        return tid\n    def complete(self, tid: int) -> None:\n        self._todos[tid].completed = True\n    def list_open(self):\n        return [t for t in self._todos.values() if not t.completed]\n    def all(self):\n        return list(self._todos.values())\n''',
        "src/v04/mf04/filters.py": '''"""Todo filters (explicit now -- no wall clock)."""\nfrom __future__ import annotations\n\ndef overdue(todos, now_ts: float):\n    return [t for t in todos if not t.completed and t.due_ts < now_ts]\n''',
        "src/v04/mf04/stats.py": '''"""Todo statistics."""\nfrom __future__ import annotations\n\ndef completion_rate(todos) -> float:\n    if not todos:\n        return 0.0\n    done = sum(1 for t in todos if t.completed)\n    return done / len(todos)\n''',
    },
    {"src/v04/mf04/store.py": "def broken(:\n"},
    {"src/v04/mf04/filters.py": '''"""Todo filters -- BROKEN: never reports overdue."""\nfrom __future__ import annotations\n\ndef overdue(todos, now_ts: float):\n    return []\n'''},
)

# =====================================================================
# MF-05: text pipeline (tokenize / normalize / count)
# =====================================================================
T(
    "v04_mf_05", "V04 Text Pipeline Tokenize/Normalize/Count", "multifile",
    [
        ("v04_mf_05_tok", "Tokenizer", ["src/v04/mf05/tokenize.py"], []),
        ("v04_mf_05_norm", "Normalizer", ["src/v04/mf05/normalize.py"], ["v04_mf_05_tok"]),
        ("v04_mf_05_count", "Word Counter", ["src/v04/mf05/count.py"], ["v04_mf_05_norm"]),
    ],
    '''"""Pins v04_mf_05: tokenize -> normalize -> count pipeline composition."""\nfrom src.v04.mf05.tokenize import tokenize\nfrom src.v04.mf05.normalize import normalize\nfrom src.v04.mf05.count import word_counts\n\ntoks = tokenize("Hello hello  WORLD\\n")\nassert toks == ["Hello", "hello", "WORLD"], toks\nnorm = normalize(toks)\nassert norm == ["hello", "hello", "world"], norm\nassert word_counts(norm) == {"hello": 2, "world": 1}\nassert normalize(["  ", "\\t"]) == []\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf05/tokenize.py": '''"""Whitespace tokenizer."""\nfrom __future__ import annotations\n\ndef tokenize(text: str):\n    return text.split()\n''',
        "src/v04/mf05/normalize.py": '''"""Token normalization."""\nfrom __future__ import annotations\n\ndef normalize(tokens):\n    return [t.strip().lower() for t in tokens if t.strip()]\n''',
        "src/v04/mf05/count.py": '''"""Word counting."""\nfrom __future__ import annotations\n\ndef word_counts(tokens):\n    d = {}\n    for t in tokens:\n        d[t] = d.get(t, 0) + 1\n    return d\n''',
    },
    {"src/v04/mf05/tokenize.py": "def broken(:\n"},
    {"src/v04/mf05/normalize.py": '''"""Token normalization -- BROKEN: no lowercasing."""\nfrom __future__ import annotations\n\ndef normalize(tokens):\n    return [t.strip() for t in tokens if t.strip()]\n'''},
)

# =====================================================================
# MF-06: inventory (product / inventory / pricing)
# =====================================================================
T(
    "v04_mf_06", "V04 Inventory Reserve/Release/Pricing", "multifile",
    [
        ("v04_mf_06_product", "Product", ["src/v04/mf06/product.py"], []),
        ("v04_mf_06_inv", "Inventory", ["src/v04/mf06/inventory.py"], ["v04_mf_06_product"]),
        ("v04_mf_06_pricing", "Pricing", ["src/v04/mf06/pricing.py"], []),
    ],
    '''"""Pins v04_mf_06: stock reserve/release with OutOfStock, discount math."""\nfrom src.v04.mf06.product import Product\nfrom src.v04.mf06.inventory import Inventory, OutOfStock\nfrom src.v04.mf06.pricing import discounted\n\ninv = Inventory()\ninv.add(Product("A", 1000, 10))\ninv.reserve("A", 4)\nassert inv.stock_of("A") == 6\ntry:\n    inv.reserve("A", 7)\n    raise AssertionError("expected OutOfStock")\nexcept OutOfStock:\n    pass\ninv.release("A", 2)\nassert inv.stock_of("A") == 8\nassert discounted(1000, 25) == 750\nassert discounted(1000, 0) == 1000\ntry:\n    discounted(100, 150)\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf06/product.py": '''"""Product value object."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\n@dataclass\nclass Product:\n    sku: str\n    price_cents: int\n    stock: int\n    def __post_init__(self):\n        if self.price_cents < 0:\n            raise ValueError("price_cents must be >= 0")\n        if self.stock < 0:\n            raise ValueError("stock must be >= 0")\n''',
        "src/v04/mf06/inventory.py": '''"""Inventory with reservations."""\nfrom __future__ import annotations\n\nclass OutOfStock(Exception):\n    pass\n\nclass Inventory:\n    def __init__(self):\n        self._products = {}\n    def add(self, product) -> None:\n        self._products[product.sku] = product\n    def stock_of(self, sku: str) -> int:\n        return self._products[sku].stock\n    def reserve(self, sku: str, qty: int) -> None:\n        p = self._products[sku]\n        if qty > p.stock:\n            raise OutOfStock(f"{sku}: want {qty}, have {p.stock}")\n        p.stock -= qty\n    def release(self, sku: str, qty: int) -> None:\n        self._products[sku].stock += qty\n''',
        "src/v04/mf06/pricing.py": '''"""Pricing math."""\nfrom __future__ import annotations\n\ndef discounted(price_cents: int, pct: float) -> int:\n    if not (0 <= pct <= 100):\n        raise ValueError("pct must be in [0, 100]")\n    return int(price_cents * (100 - pct) / 100)\n''',
    },
    {"src/v04/mf06/inventory.py": "def broken(:\n"},
    {"src/v04/mf06/inventory.py": '''"""Inventory -- BROKEN: reserve skips the stock check."""\nfrom __future__ import annotations\n\nclass OutOfStock(Exception):\n    pass\n\nclass Inventory:\n    def __init__(self):\n        self._products = {}\n    def add(self, product) -> None:\n        self._products[product.sku] = product\n    def stock_of(self, sku: str) -> int:\n        return self._products[sku].stock\n    def reserve(self, sku: str, qty: int) -> None:\n        self._products[sku].stock -= qty\n    def release(self, sku: str, qty: int) -> None:\n        self._products[sku].stock += qty\n'''},
)

# =====================================================================
# MF-07: auth tokens (tokens / verify / revocation store)
# =====================================================================
T(
    "v04_mf_07", "V04 HMAC Token Issue/Verify/Revoke", "multifile",
    [
        ("v04_mf_07_tokens", "Token Issuance", ["src/v04/mf07/tokens.py"], []),
        ("v04_mf_07_verify", "Token Verification", ["src/v04/mf07/verify.py"], ["v04_mf_07_tokens"]),
        ("v04_mf_07_store", "Revocation Store", ["src/v04/mf07/store.py"], []),
    ],
    '''"""Pins v04_mf_07: hmac token issue/verify with explicit clock; expiry, tamper, revocation."""\nfrom src.v04.mf07.tokens import issue\nfrom src.v04.mf07.verify import verify, TokenExpired, BadSignature\nfrom src.v04.mf07.store import RevocationList\n\ntok = issue("alice", ttl_s=60, now=1000.0, secret="s3cret")\nsubject, exp_s, sig = tok.split(":")\nassert verify(tok, now=1050.0, secret="s3cret") == "alice"\ntry:\n    verify(tok, now=2000.0, secret="s3cret")\n    raise AssertionError("expected TokenExpired")\nexcept TokenExpired:\n    pass\nbad = "alice:" + exp_s + ":" + "0" * 64\ntry:\n    verify(bad, now=1050.0, secret="s3cret")\n    raise AssertionError("expected BadSignature")\nexcept BadSignature:\n    pass\nrl = RevocationList()\nassert rl.is_revoked(sig) is False\nrl.revoke(sig)\nassert rl.is_revoked(sig) is True\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf07/tokens.py": '''"""Token issuance (hmac-signed)."""\nfrom __future__ import annotations\nimport hashlib\nimport hmac\n\ndef issue(subject: str, ttl_s: int, now: float, secret: str) -> str:\n    exp = int(now) + ttl_s\n    sig = hmac.new(secret.encode(), f"{subject}:{exp}".encode(), hashlib.sha256).hexdigest()\n    return f"{subject}:{exp}:{sig}"\n''',
        "src/v04/mf07/verify.py": '''"""Token verification."""\nfrom __future__ import annotations\nimport hashlib\nimport hmac\n\nclass TokenExpired(Exception):\n    pass\n\nclass BadSignature(Exception):\n    pass\n\ndef verify(token: str, now: float, secret: str) -> str:\n    try:\n        subject, exp_s, sig = token.split(":")\n        exp = int(exp_s)\n    except ValueError:\n        raise BadSignature("malformed token")\n    good = hmac.new(secret.encode(), f"{subject}:{exp}".encode(), hashlib.sha256).hexdigest()\n    if not hmac.compare_digest(good, sig):\n        raise BadSignature("signature mismatch")\n    if now > exp:\n        raise TokenExpired("token expired")\n    return subject\n''',
        "src/v04/mf07/store.py": '''"""Revocation list."""\nfrom __future__ import annotations\n\nclass RevocationList:\n    def __init__(self):\n        self._revoked = set()\n    def revoke(self, sig: str) -> None:\n        self._revoked.add(sig)\n    def is_revoked(self, sig: str) -> bool:\n        return sig in self._revoked\n''',
    },
    {"src/v04/mf07/tokens.py": "def broken(:\n"},
    {"src/v04/mf07/verify.py": '''"""Token verification -- BROKEN: expiry never checked."""\nfrom __future__ import annotations\nimport hashlib\nimport hmac\n\nclass TokenExpired(Exception):\n    pass\n\nclass BadSignature(Exception):\n    pass\n\ndef verify(token: str, now: float, secret: str) -> str:\n    try:\n        subject, exp_s, sig = token.split(":")\n        exp = int(exp_s)\n    except ValueError:\n        raise BadSignature("malformed token")\n    good = hmac.new(secret.encode(), f"{subject}:{exp}".encode(), hashlib.sha256).hexdigest()\n    if not hmac.compare_digest(good, sig):\n        raise BadSignature("signature mismatch")\n    return subject\n'''},
)

# =====================================================================
# MF-08: CSV report (parse / aggregate / render)
# =====================================================================
T(
    "v04_mf_08", "V04 CSV Parse/Aggregate/Render", "multifile",
    [
        ("v04_mf_08_parse", "CSV Parser", ["src/v04/mf08/parse.py"], []),
        ("v04_mf_08_agg", "Aggregator", ["src/v04/mf08/aggregate.py"], ["v04_mf_08_parse"]),
        ("v04_mf_08_render", "CSV Renderer", ["src/v04/mf08/render.py"], ["v04_mf_08_parse"]),
    ],
    '''"""Pins v04_mf_08: CSV parse, group-sum aggregation, render round-trip."""\nfrom src.v04.mf08.parse import parse_rows\nfrom src.v04.mf08.aggregate import sum_by_key\nfrom src.v04.mf08.render import to_csv\n\nrows = parse_rows("name,amt\\na,10\\na,20\\nb,5\\n")\nassert rows == [{"name": "a", "amt": "10"}, {"name": "a", "amt": "20"}, {"name": "b", "amt": "5"}], rows\nassert sum_by_key(rows, "name", "amt") == {"a": 30, "b": 5}\nrt = parse_rows(to_csv(rows))\nassert rt == rows, rt\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/mf08/parse.py": '''"""Minimal CSV parsing (header + rows)."""\nfrom __future__ import annotations\n\ndef parse_rows(text: str):\n    lines = [ln for ln in text.strip().splitlines() if ln.strip()]\n    header = [h.strip() for h in lines[0].split(",")]\n    rows = []\n    for ln in lines[1:]:\n        vals = [v.strip() for v in ln.split(",")]\n        rows.append(dict(zip(header, vals)))\n    return rows\n''',
        "src/v04/mf08/aggregate.py": '''"""Aggregation over parsed rows."""\nfrom __future__ import annotations\n\ndef sum_by_key(rows, group_key: str, sum_key: str):\n    totals = {}\n    for r in rows:\n        totals[r[group_key]] = totals.get(r[group_key], 0) + int(r[sum_key])\n    return totals\n''',
        "src/v04/mf08/render.py": '''"""CSV rendering."""\nfrom __future__ import annotations\n\ndef to_csv(rows) -> str:\n    if not rows:\n        return ""\n    header = list(rows[0].keys())\n    lines = [",".join(header)]\n    for r in rows:\n        lines.append(",".join(str(r[h]) for h in header))\n    return "\\n".join(lines) + "\\n"\n''',
    },
    {"src/v04/mf08/parse.py": "def broken(:\n"},
    {"src/v04/mf08/aggregate.py": '''"""Aggregation -- BROKEN: no int conversion (TypeError on str)."""\nfrom __future__ import annotations\n\ndef sum_by_key(rows, group_key: str, sum_key: str):\n    totals = {}\n    for r in rows:\n        totals[r[group_key]] = totals.get(r[group_key], 0) + r[sum_key]\n    return totals\n'''},
)

# =====================================================================
# P-01: schema validator (schema / errors)
# =====================================================================
T(
    "v04_p01", "V04 Nested Schema Validation", "protocol",
    [
        ("v04_p01_schema", "Schema Validator", ["src/v04/p01/schema.py"], []),
        ("v04_p01_errors", "Error Formatter", ["src/v04/p01/errors.py"], ["v04_p01_schema"]),
    ],
    '''"""Pins v04_p01: nested schema validation with dotted error paths."""\nfrom src.v04.p01.schema import validate\nfrom src.v04.p01.errors import format_errors\n\nschema = {"name": str, "age": int, "addr": {"city": str}}\nassert validate({"name": "a", "age": 3, "addr": {"city": "x"}}, schema) == []\nassert validate({"age": 3, "addr": {"city": "x"}}, schema) == ["missing: name"]\nassert validate({"name": "a", "age": "3", "addr": {"city": "x"}}, schema) == ["age: expected int, got str"]\nassert validate({"name": "a", "age": 3, "addr": {"city": 9}}, schema) == ["addr.city: expected str, got int"]\nerrs = validate({"age": "x"}, schema)\nassert format_errors(errs) == "missing: name; age: expected int, got str; missing: addr", format_errors(errs)\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/p01/schema.py": '''"""Schema validation with dotted error paths."""\nfrom __future__ import annotations\n\ndef validate(payload: dict, schema: dict, _path: str = ""):\n    errors = []\n    for key, expected in schema.items():\n        path = f"{_path}.{key}" if _path else key\n        if key not in payload:\n            errors.append(f"missing: {path}")\n            continue\n        val = payload[key]\n        if isinstance(expected, dict):\n            if not isinstance(val, dict):\n                errors.append(f"{path}: expected object, got {type(val).__name__}")\n            else:\n                errors.extend(validate(val, expected, path))\n        elif not isinstance(val, expected):\n            errors.append(f"{path}: expected {expected.__name__}, got {type(val).__name__}")\n    return errors\n''',
        "src/v04/p01/errors.py": '''"""Error formatting."""\nfrom __future__ import annotations\n\ndef format_errors(errors) -> str:\n    return "; ".join(errors)\n''',
    },
    {"src/v04/p01/schema.py": "def broken(:\n"},
    {"src/v04/p01/schema.py": '''"""Schema validation -- BROKEN: never reports errors."""\nfrom __future__ import annotations\n\ndef validate(payload: dict, schema: dict, _path: str = ""):\n    return []\n'''},
)

# =====================================================================
# P-02: FSM (states / fsm)
# =====================================================================
T(
    "v04_p02", "V04 FSM Transitions", "protocol",
    [
        ("v04_p02_states", "State Constants", ["src/v04/p02/states.py"], []),
        ("v04_p02_fsm", "FSM Engine", ["src/v04/p02/fsm.py"], ["v04_p02_states"]),
    ],
    '''"""Pins v04_p02: FSM transitions and illegal-transition rejection."""\nfrom src.v04.p02.states import INIT, READY, RUNNING, TERMINATED\nfrom src.v04.p02.fsm import FSM, IllegalTransition\n\nfsm = FSM({(INIT, "boot"): READY, (READY, "start"): RUNNING, (RUNNING, "stop"): TERMINATED}, INIT)\nassert fsm.trigger("boot") == READY\nassert fsm.trigger("start") == RUNNING\nassert fsm.trigger("stop") == TERMINATED\nassert fsm.state == TERMINATED\ntry:\n    fsm.trigger("boot")\n    raise AssertionError("expected IllegalTransition")\nexcept IllegalTransition:\n    pass\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/p02/states.py": '''"""FSM state constants."""\nINIT = "INIT"\nREADY = "READY"\nRUNNING = "RUNNING"\nTERMINATED = "TERMINATED"\n''',
        "src/v04/p02/fsm.py": '''"""Finite state machine."""\nfrom __future__ import annotations\n\nclass IllegalTransition(Exception):\n    pass\n\nclass FSM:\n    def __init__(self, transitions: dict, initial: str):\n        self._transitions = dict(transitions)\n        self.state = initial\n    def trigger(self, event: str) -> str:\n        key = (self.state, event)\n        if key not in self._transitions:\n            raise IllegalTransition(f"{self.state} + {event}")\n        self.state = self._transitions[key]\n        return self.state\n''',
    },
    {"src/v04/p02/fsm.py": "def broken(:\n"},
    {"src/v04/p02/fsm.py": '''"""FSM -- BROKEN: illegal transitions silently ignored."""\nfrom __future__ import annotations\n\nclass IllegalTransition(Exception):\n    pass\n\nclass FSM:\n    def __init__(self, transitions: dict, initial: str):\n        self._transitions = dict(transitions)\n        self.state = initial\n    def trigger(self, event: str) -> str:\n        key = (self.state, event)\n        if key in self._transitions:\n            self.state = self._transitions[key]\n        return self.state\n'''},
)

# =====================================================================
# P-03: audit log (audit / verify)
# =====================================================================
T(
    "v04_p03", "V04 Audit Log Monotonicity", "protocol",
    [
        ("v04_p03_audit", "Audit Log", ["src/v04/p03/audit.py"], []),
        ("v04_p03_verify", "Monotonicity Verifier", ["src/v04/p03/verify.py"], ["v04_p03_audit"]),
    ],
    '''"""Pins v04_p03: monotonic audit sequence numbers and tamper detection."""\nfrom src.v04.p03.audit import AuditLog\nfrom src.v04.p03.verify import check_monotonic\n\nlog = AuditLog()\nlog.append("login")\nlog.append("pay")\nlog.append("logout")\nents = log.entries()\nassert [e["seq"] for e in ents] == [1, 2, 3]\nassert check_monotonic(ents) is True\ntampered = [dict(e) for e in ents]\ntampered[1]["seq"] = 99\nassert check_monotonic(tampered) is False\nassert check_monotonic([]) is True\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/p03/audit.py": '''"""Append-only audit log with monotonic sequence numbers."""\nfrom __future__ import annotations\n\nclass AuditLog:\n    def __init__(self):\n        self._entries = []\n    def append(self, action: str) -> dict:\n        entry = {"seq": len(self._entries) + 1, "action": action}\n        self._entries.append(entry)\n        return entry\n    def entries(self):\n        return list(self._entries)\n''',
        "src/v04/p03/verify.py": '''"""Audit log verification."""\nfrom __future__ import annotations\n\ndef check_monotonic(entries) -> bool:\n    return [e["seq"] for e in entries] == list(range(1, len(entries) + 1))\n''',
    },
    {"src/v04/p03/audit.py": "def broken(:\n"},
    {"src/v04/p03/verify.py": '''"""Audit verification -- BROKEN: always True."""\nfrom __future__ import annotations\n\ndef check_monotonic(entries) -> bool:\n    return True\n'''},
)

# =====================================================================
# P-04: framing (frame / decode)
# =====================================================================
T(
    "v04_p04", "V04 Length-Prefixed Framing", "protocol",
    [
        ("v04_p04_frame", "Frame Encoder", ["src/v04/p04/frame.py"], []),
        ("v04_p04_decode", "Frame Decoder", ["src/v04/p04/decode.py"], ["v04_p04_frame"]),
    ],
    '''"""Pins v04_p04: length-prefixed framing round-trip and truncation detection."""\nfrom src.v04.p04.frame import encode\nfrom src.v04.p04.decode import decode_one, IncompleteFrame\n\np1, p2 = b"hello", b"world!"\nblob = encode(p1) + encode(p2)\nout1, rest = decode_one(blob)\nout2, rest2 = decode_one(rest)\nassert out1 == p1 and out2 == p2 and rest2 == b""\ntry:\n    decode_one(encode(p1)[:3])\n    raise AssertionError("expected IncompleteFrame")\nexcept IncompleteFrame:\n    pass\ntry:\n    decode_one(encode(p1)[:-1])\n    raise AssertionError("expected IncompleteFrame")\nexcept IncompleteFrame:\n    pass\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/p04/frame.py": '''"""Length-prefixed framing."""\nfrom __future__ import annotations\nimport struct\n\nMAX_FRAME = 1 << 20\n\ndef encode(payload: bytes) -> bytes:\n    if len(payload) > MAX_FRAME:\n        raise ValueError("frame too large")\n    return struct.pack(">I", len(payload)) + payload\n''',
        "src/v04/p04/decode.py": '''"""Frame decoding."""\nfrom __future__ import annotations\nimport struct\n\nclass IncompleteFrame(Exception):\n    pass\n\nclass FrameTooLarge(Exception):\n    pass\n\ndef decode_one(buf: bytes):\n    if len(buf) < 4:\n        raise IncompleteFrame("need length prefix")\n    (n,) = struct.unpack(">I", buf[:4])\n    if n > (1 << 20):\n        raise FrameTooLarge("frame too large")\n    if len(buf) < 4 + n:\n        raise IncompleteFrame("truncated payload")\n    return buf[4:4+n], buf[4+n:]\n''',
    },
    {"src/v04/p04/frame.py": "def broken(:\n"},
    {"src/v04/p04/decode.py": '''"""Frame decoding -- BROKEN: no truncation check."""\nfrom __future__ import annotations\nimport struct\n\nclass IncompleteFrame(Exception):\n    pass\n\nclass FrameTooLarge(Exception):\n    pass\n\ndef decode_one(buf: bytes):\n    (n,) = struct.unpack(">I", buf[:4])\n    return buf[4:4+n], buf[4+n:]\n'''},
)

# =====================================================================
# P-05: retry policy (policy / should_retry)
# =====================================================================
T(
    "v04_p05", "V04 Exponential Backoff and Retry Decisions", "protocol",
    [
        ("v04_p05_policy", "Backoff Policy", ["src/v04/p05/policy.py"], []),
        ("v04_p05_retry", "Retry Decisions", ["src/v04/p05/should_retry.py"], ["v04_p05_policy"]),
    ],
    '''"""Pins v04_p05: exponential backoff values and retryable-status decisions."""\nfrom src.v04.p05.policy import backoff_delay\nfrom src.v04.p05.should_retry import should_retry\n\nassert backoff_delay(0) == 1.0\nassert backoff_delay(1) == 2.0\nassert backoff_delay(2) == 4.0\nassert backoff_delay(10) == 30.0\nassert backoff_delay(3, base=0.5, cap=1.0) == 1.0\nassert should_retry(503, 0, 3) is True\nassert should_retry(429, 2, 3) is True\nassert should_retry(404, 0, 3) is False\nassert should_retry(400, 0, 3) is False\nassert should_retry(503, 3, 3) is False\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/p05/policy.py": '''"""Exponential backoff."""\nfrom __future__ import annotations\n\ndef backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:\n    return min(cap, base * (2 ** attempt))\n''',
        "src/v04/p05/should_retry.py": '''"""Retry decisions."""\nfrom __future__ import annotations\n\ndef should_retry(status: int, attempt: int, max_attempts: int) -> bool:\n    if attempt >= max_attempts:\n        return False\n    if status == 429 or 500 <= status <= 599:\n        return True\n    return False\n''',
    },
    {"src/v04/p05/policy.py": "def broken(:\n"},
    {"src/v04/p05/policy.py": '''"""Backoff -- BROKEN: constant delay."""\nfrom __future__ import annotations\n\ndef backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:\n    return base\n'''},
)

# =====================================================================
# P-06: pagination (cursor / page)
# =====================================================================
T(
    "v04_p06", "V04 Cursor Pagination", "protocol",
    [
        ("v04_p06_cursor", "Cursor Codec", ["src/v04/p06/cursor.py"], []),
        ("v04_p06_page", "Paginator", ["src/v04/p06/page.py"], ["v04_p06_cursor"]),
    ],
    '''"""Pins v04_p06: cursor pagination covers items exactly once; bad cursor rejected."""\nfrom src.v04.p06.cursor import encode, decode, BadCursor\nfrom src.v04.p06.page import paginate\n\nitems = list(range(10))\nseen = []\ncur = None\nwhile True:\n    page, cur = paginate(items, 3, cur)\n    seen.extend(page)\n    if cur is None:\n        break\nassert seen == items, seen\np1, c1 = paginate(items, 4)\nassert p1 == [0, 1, 2, 3] and c1 is not None\np2, c2 = paginate(items, 4, c1)\nassert p2 == [4, 5, 6, 7]\np3, c3 = paginate(items, 4, c2)\nassert p3 == [8, 9] and c3 is None\ntry:\n    decode("!!!not-a-cursor!!!")\n    raise AssertionError("expected BadCursor")\nexcept BadCursor:\n    pass\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/p06/cursor.py": '''"""Opaque pagination cursors."""\nfrom __future__ import annotations\nimport base64\n\nclass BadCursor(Exception):\n    pass\n\ndef encode(offset: int) -> str:\n    return base64.urlsafe_b64encode(str(offset).encode()).decode()\n\ndef decode(s: str) -> int:\n    try:\n        return int(base64.urlsafe_b64decode(s.encode()).decode())\n    except Exception:\n        raise BadCursor(f"bad cursor: {s!r}")\n''',
        "src/v04/p06/page.py": '''"""Pagination."""\nfrom __future__ import annotations\nfrom src.v04.p06.cursor import encode, decode\n\ndef paginate(items, page_size: int, cursor=None):\n    offset = decode(cursor) if cursor else 0\n    page = items[offset:offset + page_size]\n    nxt = offset + page_size\n    next_cursor = encode(nxt) if nxt < len(items) else None\n    return page, next_cursor\n''',
    },
    {"src/v04/p06/cursor.py": "def broken(:\n"},
    {"src/v04/p06/page.py": '''"""Pagination -- BROKEN: cursor ignored, always first page."""\nfrom __future__ import annotations\nfrom src.v04.p06.cursor import encode, decode\n\ndef paginate(items, page_size: int, cursor=None):\n    return items[0:page_size], None\n'''},
)

# =====================================================================
# C-01: atomic counter (counter / workers)
# =====================================================================
T(
    "v04_c01", "V04 Atomic Counter Under Threads", "concurrency",
    [
        ("v04_c01_counter", "Atomic Counter", ["src/v04/c01/counter.py"], []),
        ("v04_c01_workers", "Thread Workers", ["src/v04/c01/workers.py"], ["v04_c01_counter"]),
    ],
    '''"""Pins v04_c01: 20 threads x 100 increments land exactly on 2000."""\nfrom src.v04.c01.counter import AtomicCounter\nfrom src.v04.c01.workers import run_workers\n\nc = AtomicCounter()\nrun_workers(c, n_threads=20, n_incr=100)\nassert c.value == 2000, c.value\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/c01/counter.py": '''"""Thread-safe counter."""\nfrom __future__ import annotations\nimport threading\n\nclass AtomicCounter:\n    def __init__(self):\n        self._lock = threading.Lock()\n        self._value = 0\n    def incr(self, n: int = 1) -> None:\n        with self._lock:\n            self._value += n\n    @property\n    def value(self) -> int:\n        with self._lock:\n            return self._value\n''',
        "src/v04/c01/workers.py": '''"""Thread workers driving a shared counter."""\nfrom __future__ import annotations\nimport threading\n\ndef run_workers(counter, n_threads: int, n_incr: int) -> None:\n    def work():\n        for _ in range(n_incr):\n            counter.incr()\n    threads = [threading.Thread(target=work) for _ in range(n_threads)]\n    for t in threads:\n        t.start()\n    for t in threads:\n        t.join()\n''',
    },
    {"src/v04/c01/counter.py": "def broken(:\n"},
    {"src/v04/c01/counter.py": '''"""Counter -- BROKEN: incr adds n+1."""\nfrom __future__ import annotations\nimport threading\n\nclass AtomicCounter:\n    def __init__(self):\n        self._lock = threading.Lock()\n        self._value = 0\n    def incr(self, n: int = 1) -> None:\n        with self._lock:\n            self._value += n + 1\n    @property\n    def value(self) -> int:\n        with self._lock:\n            return self._value\n'''},
)

# =====================================================================
# C-02: producer/consumer (channel / pipeline)
# =====================================================================
T(
    "v04_c02", "V04 Producer Consumer Pipeline", "concurrency",
    [
        ("v04_c02_channel", "Closeable Channel", ["src/v04/c02/channel.py"], []),
        ("v04_c02_pipeline", "Pipeline", ["src/v04/c02/pipeline.py"], ["v04_c02_channel"]),
    ],
    '''"""Pins v04_c02: 100 items through 4 consumers exactly once; close semantics."""\nfrom src.v04.c02.channel import Channel, ChannelClosed\nfrom src.v04.c02.pipeline import run_pipeline\n\nout = run_pipeline(list(range(100)), n_consumers=4)\nassert sorted(out) == list(range(100)), len(out)\nch = Channel()\nch.put("x")\nch.close()\nassert ch.get() == "x"\ntry:\n    ch.put("y")\n    raise AssertionError("expected ChannelClosed")\nexcept ChannelClosed:\n    pass\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/c02/channel.py": '''"""Closeable channel."""\nfrom __future__ import annotations\nimport queue\n\nclass ChannelClosed(Exception):\n    pass\n\nclass Channel:\n    def __init__(self):\n        self._q = queue.Queue()\n        self._closed = False\n    def put(self, item) -> None:\n        if self._closed:\n            raise ChannelClosed("put on closed channel")\n        self._q.put(item)\n    def get(self):\n        try:\n            return self._q.get(timeout=5)\n        except queue.Empty:\n            raise ChannelClosed("get on drained channel")\n    def close(self) -> None:\n        self._closed = True\n    def empty(self) -> bool:\n        return self._q.empty()\n''',
        "src/v04/c02/pipeline.py": '''"""Threaded producer/consumer pipeline."""\nfrom __future__ import annotations\nimport threading\nfrom src.v04.c02.channel import Channel\n\n_SENTINEL = object()\n\ndef run_pipeline(items, n_consumers: int):\n    ch = Channel()\n    out = []\n    lock = threading.Lock()\n    def consumer():\n        while True:\n            item = ch.get()\n            if item is _SENTINEL:\n                return\n            with lock:\n                out.append(item)\n    cons = [threading.Thread(target=consumer) for _ in range(n_consumers)]\n    for t in cons:\n        t.start()\n    for it in items:\n        ch.put(it)\n    for _ in range(n_consumers):\n        ch.put(_SENTINEL)\n    for t in cons:\n        t.join()\n    return out\n''',
    },
    {"src/v04/c02/channel.py": "def broken(:\n"},
    {"src/v04/c02/pipeline.py": '''"""Pipeline -- BROKEN: drops every 10th item."""\nfrom __future__ import annotations\nimport threading\nfrom src.v04.c02.channel import Channel\n\n_SENTINEL = object()\n\ndef run_pipeline(items, n_consumers: int):\n    ch = Channel()\n    out = []\n    lock = threading.Lock()\n    def consumer():\n        while True:\n            item = ch.get()\n            if item is _SENTINEL:\n                return\n            with lock:\n                out.append(item)\n    cons = [threading.Thread(target=consumer) for _ in range(n_consumers)]\n    for t in cons:\n        t.start()\n    for i, it in enumerate(items):\n        if i % 10 == 9:\n            continue\n        ch.put(it)\n    for _ in range(n_consumers):\n        ch.put(_SENTINEL)\n    for t in cons:\n        t.join()\n    return out\n'''},
)

# =====================================================================
# C-03: TTL cache (cache / evict)
# =====================================================================
T(
    "v04_c03", "V04 TTL Cache with Injected Clock", "concurrency",
    [
        ("v04_c03_cache", "TTL Cache", ["src/v04/c03/cache.py"], []),
        ("v04_c03_evict", "Expiry Eviction", ["src/v04/c03/evict.py"], ["v04_c03_cache"]),
    ],
    '''"""Pins v04_c03: TTL expiry with injected clock; eviction counts."""\nfrom src.v04.c03.cache import TTLCache, KeyExpired\nfrom src.v04.c03.evict import evict_expired\n\nclass FakeClock:\n    def __init__(self):\n        self.t = 0.0\n    def __call__(self):\n        return self.t\n\nclk = FakeClock()\nc = TTLCache(clock=clk)\nc.set("a", 1, ttl_s=10)\nc.set("b", 2, ttl_s=100)\nassert c.get("a") == 1\nclk.t = 11.0\ntry:\n    c.get("a")\n    raise AssertionError("expected KeyExpired")\nexcept KeyExpired:\n    pass\nassert c.get("b") == 2\n# the expired get() above already removed "a"; add a fresh expired key for eviction\nc.set("c", 3, ttl_s=1)\nclk.t = 13.0\nassert evict_expired(c) == 1\nassert len(c) == 1\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/c03/cache.py": '''"""TTL cache with injectable clock."""\nfrom __future__ import annotations\nimport time\n\nclass KeyExpired(Exception):\n    pass\n\nclass TTLCache:\n    def __init__(self, clock=None):\n        self._clock = clock or time.monotonic\n        self._data = {}\n    def set(self, key, value, ttl_s: float) -> None:\n        self._data[key] = (value, self._clock() + ttl_s)\n    def get(self, key):\n        if key not in self._data:\n            raise KeyError(key)\n        value, exp = self._data[key]\n        if self._clock() > exp:\n            del self._data[key]\n            raise KeyExpired(key)\n        return value\n    def keys(self):\n        return list(self._data.keys())\n    def __len__(self):\n        return len(self._data)\n''',
        "src/v04/c03/evict.py": '''"""Expiry eviction."""\nfrom __future__ import annotations\nfrom src.v04.c03.cache import KeyExpired\n\ndef evict_expired(cache) -> int:\n    removed = 0\n    for k in cache.keys():\n        try:\n            cache.get(k)\n        except KeyExpired:\n            removed += 1\n        except KeyError:\n            pass\n    return removed\n''',
    },
    {"src/v04/c03/cache.py": "def broken(:\n"},
    {"src/v04/c03/cache.py": '''"""TTL cache -- BROKEN: get ignores TTL."""\nfrom __future__ import annotations\nimport time\n\nclass KeyExpired(Exception):\n    pass\n\nclass TTLCache:\n    def __init__(self, clock=None):\n        self._clock = clock or time.monotonic\n        self._data = {}\n    def set(self, key, value, ttl_s: float) -> None:\n        self._data[key] = (value, self._clock() + ttl_s)\n    def get(self, key):\n        if key not in self._data:\n            raise KeyError(key)\n        value, exp = self._data[key]\n        return value\n    def keys(self):\n        return list(self._data.keys())\n    def __len__(self):\n        return len(self._data)\n'''},
)

# =====================================================================
# C-04: barrier (barrier / collect)
# =====================================================================
T(
    "v04_c04", "V04 Reusable Barrier and Ordered Gather", "concurrency",
    [
        ("v04_c04_barrier", "Reusable Barrier", ["src/v04/c04/barrier.py"], []),
        ("v04_c04_collect", "Ordered Gather", ["src/v04/c04/collect.py"], ["v04_c04_barrier"]),
    ],
    '''"""Pins v04_c04: barrier synchronizes 5 threads across 2 rounds; gather preserves order."""\nimport threading\nfrom src.v04.c04.barrier import Barrier\nfrom src.v04.c04.collect import gather\n\nb = Barrier(5)\npassed = []\nlock = threading.Lock()\ndef worker(i):\n    for _ in range(2):\n        b.wait()\n    with lock:\n        passed.append(i)\nthreads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]\nfor t in threads:\n    t.start()\nfor t in threads:\n    t.join(timeout=5)\nassert not any(t.is_alive() for t in threads), "barrier deadlock"\nassert sorted(passed) == [0, 1, 2, 3, 4]\nassert gather([lambda: 1, lambda: 2, lambda: 3]) == [1, 2, 3]\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/c04/barrier.py": '''"""Reusable barrier."""\nfrom __future__ import annotations\nimport threading\n\nclass Barrier:\n    def __init__(self, n: int):\n        self._n = n\n        self._count = 0\n        self._cond = threading.Condition()\n        self._round = 0\n    def wait(self) -> None:\n        with self._cond:\n            round_ = self._round\n            self._count += 1\n            if self._count == self._n:\n                self._count = 0\n                self._round += 1\n                self._cond.notify_all()\n            else:\n                while self._round == round_:\n                    self._cond.wait()\n''',
        "src/v04/c04/collect.py": '''"""Threaded gather preserving order."""\nfrom __future__ import annotations\nimport threading\n\ndef gather(fns):\n    results = [None] * len(fns)\n    def run(i, fn):\n        results[i] = fn()\n    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]\n    for t in threads:\n        t.start()\n    for t in threads:\n        t.join()\n    return results\n''',
    },
    {"src/v04/c04/barrier.py": "def broken(:\n"},
    {"src/v04/c04/barrier.py": '''"""Barrier -- BROKEN: single-use only, raises on reuse."""\nfrom __future__ import annotations\nimport threading\n\nclass Barrier:\n    def __init__(self, n: int):\n        self._n = n\n        self._count = 0\n        self._uses = 0\n        self._cond = threading.Condition()\n        self._round = 0\n    def wait(self) -> None:\n        with self._cond:\n            self._uses += 1\n            if self._uses > self._n:\n                raise RuntimeError("barrier single-use only")\n            round_ = self._round\n            self._count += 1\n            if self._count == self._n:\n                self._count = 0\n                self._round += 1\n                self._cond.notify_all()\n            else:\n                while self._round == round_:\n                    self._cond.wait()\n'''},
)

# =====================================================================
# C-05: token bucket (bucket / api)
# =====================================================================
T(
    "v04_c05", "V04 Token Bucket Rate Limiter", "concurrency",
    [
        ("v04_c05_bucket", "Token Bucket", ["src/v04/c05/bucket.py"], []),
        ("v04_c05_api", "Limited Calls", ["src/v04/c05/api.py"], ["v04_c05_bucket"]),
    ],
    '''"""Pins v04_c05: token bucket with fake clock; limited calls."""\nfrom src.v04.c05.bucket import TokenBucket\nfrom src.v04.c05.api import call_limited, RateLimited\n\nclass FakeClock:\n    def __init__(self):\n        self.t = 0.0\n    def __call__(self):\n        return self.t\n\nclk = FakeClock()\nb = TokenBucket(rate_per_s=1.0, capacity=3, clock=clk)\nassert [b.take() for _ in range(3)] == [True, True, True]\nassert b.take() is False\nclk.t = 1.5\nassert b.take() is True\nassert b.take() is False\ntry:\n    call_limited(b, lambda: "ok")\n    raise AssertionError("expected RateLimited")\nexcept RateLimited:\n    pass\nclk.t = 3.0\nassert call_limited(b, lambda: "ok") == "ok"\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/c05/bucket.py": '''"""Token bucket with injectable clock."""\nfrom __future__ import annotations\nimport time\n\nclass TokenBucket:\n    def __init__(self, rate_per_s: float, capacity: int, clock=None):\n        self._rate = rate_per_s\n        self._capacity = capacity\n        self._tokens = float(capacity)\n        self._clock = clock or time.monotonic\n        self._last = self._clock()\n    def take(self, n: int = 1) -> bool:\n        now = self._clock()\n        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)\n        self._last = now\n        if self._tokens >= n:\n            self._tokens -= n\n            return True\n        return False\n''',
        "src/v04/c05/api.py": '''"""Rate-limited calls."""\nfrom __future__ import annotations\n\nclass RateLimited(Exception):\n    pass\n\ndef call_limited(bucket, fn):\n    if bucket.take():\n        return fn()\n    raise RateLimited("rate limit exceeded")\n''',
    },
    {"src/v04/c05/bucket.py": "def broken(:\n"},
    {"src/v04/c05/bucket.py": '''"""Token bucket -- BROKEN: take always succeeds."""\nfrom __future__ import annotations\nimport time\n\nclass TokenBucket:\n    def __init__(self, rate_per_s: float, capacity: int, clock=None):\n        self._rate = rate_per_s\n        self._capacity = capacity\n        self._tokens = float(capacity)\n        self._clock = clock or time.monotonic\n        self._last = self._clock()\n    def take(self, n: int = 1) -> bool:\n        return True\n'''},
)

# =====================================================================
# C-06: RW lock store (rwlock / store)
# =====================================================================
T(
    "v04_c06", "V04 RWLock Shared Store", "concurrency",
    [
        ("v04_c06_rwlock", "RWLock", ["src/v04/c06/rwlock.py"], []),
        ("v04_c06_store", "Shared Store", ["src/v04/c06/store.py"], ["v04_c06_rwlock"]),
    ],
    '''"""Pins v04_c06: 10 readers + 1 writer x 50 writes; no lost updates."""\nimport threading\nfrom src.v04.c06.rwlock import RWLock\nfrom src.v04.c06.store import SharedStore\n\ns = SharedStore()\ndef writer():\n    for i in range(1, 51):\n        s.write("k", i)\ndef reader():\n    for _ in range(200):\n        s.read("k")\nthreads = [threading.Thread(target=writer)]\nthreads += [threading.Thread(target=reader) for _ in range(10)]\nfor t in threads:\n    t.start()\nfor t in threads:\n    t.join(timeout=10)\nassert not any(t.is_alive() for t in threads), "deadlock"\nassert s.read("k") == 50, s.read("k")\nprint("EVAL_PASSED")\n''',
    {
        "src/v04/c06/rwlock.py": '''"""Read-write lock."""\nfrom __future__ import annotations\nimport threading\nfrom contextlib import contextmanager\n\nclass RWLock:\n    def __init__(self):\n        self._lock = threading.Lock()\n        self._readers = 0\n        self._read_ok = threading.Condition(self._lock)\n        self._writer = False\n    @contextmanager\n    def read(self):\n        with self._lock:\n            while self._writer:\n                self._read_ok.wait()\n            self._readers += 1\n        try:\n            yield\n        finally:\n            with self._lock:\n                self._readers -= 1\n                if self._readers == 0:\n                    self._read_ok.notify_all()\n    @contextmanager\n    def write(self):\n        with self._lock:\n            while self._writer or self._readers > 0:\n                self._read_ok.wait()\n            self._writer = True\n        try:\n            yield\n        finally:\n            with self._lock:\n                self._writer = False\n                self._read_ok.notify_all()\n''',
        "src/v04/c06/store.py": '''"""Shared store guarded by RWLock."""\nfrom __future__ import annotations\nfrom src.v04.c06.rwlock import RWLock\n\nclass SharedStore:\n    def __init__(self):\n        self._rw = RWLock()\n        self._data = {}\n    def read(self, key):\n        with self._rw.read():\n            return self._data.get(key)\n    def write(self, key, value):\n        with self._rw.write():\n            self._data[key] = value\n''',
    },
    {"src/v04/c06/rwlock.py": "def broken(:\n"},
    {"src/v04/c06/store.py": '''"""Shared store -- BROKEN: read always returns None."""\nfrom __future__ import annotations\nfrom src.v04.c06.rwlock import RWLock\n\nclass SharedStore:\n    def __init__(self):\n        self._rw = RWLock()\n        self._data = {}\n    def read(self, key):\n        with self._rw.read():\n            return None\n    def write(self, key, value):\n        with self._rw.write():\n            self._data[key] = value\n'''},
)

# =====================================================================
# Emitter
# =====================================================================
def emit():
    base = os.path.join(HERE, "benchmarks", "v04_pilot")
    assert len(TASKS) == 20, f"expected 20 tasks, got {len(TASKS)}"
    cohorts = {}
    for t in TASKS:
        cohorts[t["cohort"]] = cohorts.get(t["cohort"], 0) + 1
    assert cohorts == {"multifile": 8, "protocol": 6, "concurrency": 6}, cohorts

    task_dicts = []
    for t in TASKS:
        owns_all = [p for _, _, owns, _ in t["nodes"] for p in owns]
        # sanity: every owns path has a reference implementation
        for p in owns_all:
            assert p in t["ref"], f"{t['task_id']}: owns {p} missing from ref"
        for variant in ("broken_v1", "broken_v2"):
            for p in t[variant]:
                assert p in t["ref"], f"{t['task_id']}: {variant} overlays unknown {p}"
        # sanity: fixture references at least one owns stem (anti-vacuity)
        stems = [os.path.splitext(os.path.basename(p))[0] for p in owns_all]
        assert any(s in t["fixture"] for s in stems), f"{t['task_id']}: fixture vacuous!"

        fx_name = f"fixtures/{t['task_id']}.py"
        fx_path = os.path.join(base, fx_name)
        os.makedirs(os.path.dirname(fx_path), exist_ok=True)
        with open(fx_path, "w") as f:
            f.write(t["fixture"])

        ref_base = os.path.join(base, "reference", t["task_id"])
        for p, content in t["ref"].items():
            fp = os.path.join(ref_base, p)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w") as f:
                f.write(content)

        for variant in ("broken_v1", "broken_v2"):
            vdir = os.path.join(base, "broken", t["task_id"], variant)
            for p, content in t[variant].items():
                fp = os.path.join(vdir, p)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w") as f:
                    f.write(content)

        task_dicts.append({
            "task_id": t["task_id"],
            "title": t["title"],
            "tier": "pilot",
            "cohort": t["cohort"],
            "is_feasible": True,
            "difficulty_dimension": "standard",
            "initial_nodes": [
                {"id": nid, "title": ntitle, "owns": owns, "needs": needs}
                for nid, ntitle, owns, needs in t["nodes"]
            ],
            "expected_gates": "",
            "fixture_file": fx_name,
            "contracts": [],
        })

    with open(os.path.join(base, "tasks.json"), "w") as f:
        json.dump(task_dicts, f, indent=2)
    print(f"emitted {len(task_dicts)} tasks -> {base}")
    print("cohorts:", cohorts)


if __name__ == "__main__":
    emit()
