"""AECP artifact-exclusive communication protocol tests.

Covers: KnowledgeArtifact publish with passing/failing/malformed witnesses,
scope-triggered delivery (exact scope, enclosing directory, GLOBAL, and
non-matching), flag->rerun->refute lifecycle, ContractArtifact revise/
acknowledge stale-consumer sync, AgentResponse publish-loop wiring,
scope delivery into dispatch context, state.json round-trip persistence,
and PUBLISH_KNOWLEDGE / FLAG_KNOWLEDGE protocol actions with guards.
"""

import json
import sys
from pathlib import Path

import pytest

from dafg.artifacts import (
    ArtifactState,
    ArtifactStore,
    ContractArtifact,
    ContractSymbol,
    KnowledgeArtifact,
    ScopeKind,
    WitnessRefutedError,
    WitnessRejectedError,
)
from dafg.protocol import Action, IllegalTransitionError, ProtocolCommand, ProtocolEngine
from dafg.runtime import AgentResponse, DAFG, StateStore, TaskNode


PY = sys.executable


def _passing_witness(marker="KG:REACHED"):
    return {"command": [PY, "-c", f"print('{marker}')"], "marker": marker, "timeout_s": 30}


def _failing_witness(marker="KG:REACHED"):
    # Witness prints the marker, then fails -> claim is REFUTED.
    return {"command": [PY, "-c", f"print('{marker}'); raise SystemExit(1)"], "marker": marker, "timeout_s": 30}


def _malformed_witness():
    return {"command": "not-an-argv-list", "marker": "KG:REACHED", "timeout_s": 30}


def _ka(claim="claim", kind=ScopeKind.FILE, scope="src/a.py", witness=None):
    return KnowledgeArtifact(claim=claim, scope_kind=kind, scope=scope, witness=witness, producer="n1")


# --- ArtifactStore.publish -------------------------------------------------


def test_publish_with_passing_witness_marks_witness_checked(tmp_path):
    store = ArtifactStore()
    ka = _ka(witness=_passing_witness())
    store.publish(ka, str(tmp_path))
    assert ka.state == ArtifactState.WITNESS_CHECKED
    assert store.artifacts[ka.artifact_id] is ka


def test_publish_with_failing_witness_rejects_and_marks_refuted(tmp_path):
    store = ArtifactStore()
    ka = _ka(witness=_failing_witness())
    with pytest.raises(WitnessRefutedError):
        store.publish(ka, str(tmp_path))
    assert ka.state == ArtifactState.REFUTED
    assert ka.artifact_id not in store.artifacts
    assert any("refuted" in e.lower() for e in store.history())


def test_publish_with_malformed_witness_raises_value_error(tmp_path):
    store = ArtifactStore()
    ka = _ka(witness=_malformed_witness())
    with pytest.raises(WitnessRejectedError):
        store.publish(ka, str(tmp_path))
    assert ka.artifact_id not in store.artifacts


def test_publish_without_witness_stores_unchecked(tmp_path):
    store = ArtifactStore()
    ka = _ka()
    store.publish(ka, str(tmp_path))
    assert ka.state == ArtifactState.UNCHECKED
    assert store.artifacts[ka.artifact_id] is ka


def test_witness_timeout_rejects_publication(tmp_path):
    store = ArtifactStore()
    ka = _ka(witness={"command": [PY, "-c", "import time; time.sleep(5)"], "marker": "KG:REACHED", "timeout_s": 1})
    with pytest.raises(WitnessRefutedError):
        store.publish(ka, str(tmp_path))
    assert ka.state == ArtifactState.REFUTED


# --- deliver: scope matching ------------------------------------------------


def test_deliver_exact_file_scope(tmp_path):
    store = ArtifactStore()
    store.publish(_ka(scope="src/a.py"), str(tmp_path))
    got = store.deliver(ScopeKind.FILE, "src/a.py")
    assert len(got) == 1
    assert got[0].claim == "claim"


def test_deliver_enclosing_directory_fallback(tmp_path):
    store = ArtifactStore()
    store.publish(_ka(kind=ScopeKind.DIRECTORY, scope="src/dafg"), str(tmp_path))
    got = store.deliver(ScopeKind.FILE, "src/dafg/runtime.py")
    assert len(got) == 1


def test_deliver_global_matches_everything(tmp_path):
    store = ArtifactStore()
    store.publish(_ka(kind=ScopeKind.GLOBAL, scope=""), str(tmp_path))
    assert len(store.deliver(ScopeKind.FILE, "anything/at/all.py")) == 1
    assert len(store.deliver(ScopeKind.SYMBOL, "some_symbol")) == 1


def test_deliver_non_matching_scope_returns_nothing(tmp_path):
    store = ArtifactStore()
    store.publish(_ka(kind=ScopeKind.FILE, scope="src/a.py"), str(tmp_path))
    store.publish(_ka(kind=ScopeKind.DIRECTORY, scope="src/other"), str(tmp_path))
    store.publish(_ka(kind=ScopeKind.SYMBOL, scope="foo", claim="sym"), str(tmp_path))
    assert store.deliver(ScopeKind.FILE, "src/b.py") == []
    assert store.deliver(ScopeKind.SYMBOL, "bar") == []


def test_deliver_excludes_refuted_artifacts(tmp_path):
    store = ArtifactStore()
    ka = _ka(scope="src/a.py", witness=_failing_witness())
    with pytest.raises(WitnessRefutedError):
        store.publish(ka, str(tmp_path))
    # Rejected at publish: not stored at all.
    assert store.deliver(ScopeKind.FILE, "src/a.py") == []
    # Refuted after storage: excluded from delivery, retained in audit.
    ka2 = _ka(scope="src/a.py", witness=_passing_witness(), claim="later")
    store.publish(ka2, str(tmp_path))
    ka2.witness = _failing_witness()
    store.flag(ka2.artifact_id, "suspicious", str(tmp_path))
    assert ka2.state == ArtifactState.REFUTED
    assert store.deliver(ScopeKind.FILE, "src/a.py") == []
    assert ka2.artifact_id in store.artifacts  # retained for audit


# --- flag lifecycle ----------------------------------------------------------


def test_flag_passing_witness_keeps_claim(tmp_path):
    store = ArtifactStore()
    ka = _ka(witness=_passing_witness())
    store.publish(ka, str(tmp_path))
    store.flag(ka.artifact_id, "double-check", str(tmp_path))
    assert ka.state == ArtifactState.WITNESS_CHECKED
    assert len(store.deliver(ScopeKind.FILE, "src/a.py")) == 1


def test_flag_unknown_artifact_raises_key_error(tmp_path):
    store = ArtifactStore()
    with pytest.raises(KeyError):
        store.flag("nope", "reason", str(tmp_path))


def test_flag_without_witness_keeps_unchecked(tmp_path):
    store = ArtifactStore()
    ka = _ka()
    store.publish(ka, str(tmp_path))
    store.flag(ka.artifact_id, "reason", str(tmp_path))
    assert ka.state == ArtifactState.UNCHECKED


# --- ContractArtifact --------------------------------------------------------


def test_contract_revise_marks_consumers_stale_then_acknowledge_clears():
    c = ContractArtifact(
        module="m1",
        symbols=[ContractSymbol(name="f", kind="function", signature="f(x: int) -> int")],
        purpose="math",
    )
    c.register_consumer("n1")
    c.register_consumer("n2")
    assert not c.is_stale("n1")
    affected = c.revise(symbols=[ContractSymbol(name="f", kind="function", signature="f(x: str) -> int")], reason="sig change")
    assert affected == {"n1", "n2"}
    assert c.revision == 2
    assert c.is_stale("n1") and c.is_stale("n2")
    c.acknowledge("n1")
    assert not c.is_stale("n1")
    assert c.is_stale("n2")


def test_contract_round_trip():
    c = ContractArtifact(
        module="m1",
        symbols=[ContractSymbol(name="f", kind="function", signature="f()", semantics="does f")],
        dependencies=["m0"],
    )
    c.register_consumer("n1")
    c2 = ContractArtifact.from_dict(c.to_dict())
    assert c2.module == "m1"
    assert c2.symbols[0].signature == "f()"
    assert c2.consumers == {"n1"}
    assert c2.revision == 1


# --- runtime wiring ----------------------------------------------------------


def _node(nid="n1", owns=("src/a.py",)):
    return TaskNode(id=nid, title=nid, owns=list(owns))


def test_agent_response_carries_knowledge_artifacts():
    r = AgentResponse(knowledge_artifacts=[_ka().to_dict()])
    d = r.to_dict()
    assert "knowledge_artifacts" in d
    r2 = AgentResponse.from_dict(d)
    assert len(r2.knowledge_artifacts) == 1


def test_publish_knowledge_guards_producer_and_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = DAFG(nodes={"n1": _node()})
    ka = _ka(witness=_passing_witness())
    out = g.publish_knowledge(g.nodes["n1"], ka)
    assert out.state == ArtifactState.WITNESS_CHECKED
    # scope outside OWNS -> rejected
    bad = _ka(scope="elsewhere/b.py", witness=_passing_witness())
    with pytest.raises(IllegalTransitionError):
        g.publish_knowledge(g.nodes["n1"], bad)
    # producer mismatch -> rejected
    other = _ka(witness=_passing_witness())
    other.producer = "n2"
    with pytest.raises(IllegalTransitionError):
        g.publish_knowledge(g.nodes["n1"], other)


def test_deliver_knowledge_scoped_to_owns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = DAFG(nodes={"n1": _node(owns=("src/a.py",)), "n2": _node("n2", owns=("src/b.py",))})
    g.publish_knowledge(g.nodes["n1"], _ka(scope="src/a.py", witness=_passing_witness(), claim="a-fact"))
    ka2 = _ka(scope="src/b.py", witness=_passing_witness(), claim="b-fact")
    ka2.producer = "n2"
    g.publish_knowledge(g.nodes["n2"], ka2)
    got = g.deliver_knowledge(g.nodes["n1"])
    assert [a.claim for a in got] == ["a-fact"]


def test_check_input_manifest_injects_delivery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = DAFG(nodes={"n1": _node()})
    g.publish_knowledge(g.nodes["n1"], _ka(scope="src/a.py", witness=_passing_witness(), claim="a-fact"))
    node = g.nodes["n1"]
    node.manifest = None
    # with no manifest it is valid; delivery happens through dispatch context instead
    g2_node_ok, _ = g.check_input_manifest(node)
    assert g2_node_ok
    from dafg.runtime import InputManifest
    node.manifest = InputManifest(required_inputs=[])
    ok, _ = g.check_input_manifest(node)
    assert ok
    delivered = node.metadata.get("delivered_knowledge", [])
    assert [a["claim"] for a in delivered] == ["a-fact"]


def test_revise_artifact_contract_stales_consumers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = DAFG(nodes={"n1": _node(), "n2": _node("n2", owns=("src/b.py",))})
    c = ContractArtifact(module="m1", symbols=[ContractSymbol(name="f", kind="function", signature="f()")])
    assert g.register_artifact_contract(c)
    g.subscribe_artifact_contract(c.contract_id, "n1")
    g.subscribe_artifact_contract(c.contract_id, "n2")
    affected = g.revise_artifact_contract(c.contract_id, reason="sig change")
    assert sorted(affected) == ["n1", "n2"]
    from dafg.protocol import ProtocolState
    assert g.nodes["n1"].protocol_state == ProtocolState.STALE
    assert g.artifact_contracts[c.contract_id].is_stale("n1")
    g.acknowledge_artifact_contract(c.contract_id, "n1")
    assert not g.artifact_contracts[c.contract_id].is_stale("n1")


def test_state_json_round_trip_preserves_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_file = tmp_path / "state.json"
    g = DAFG(nodes={"n1": _node()}, state_path=state_file)
    g.publish_knowledge(g.nodes["n1"], _ka(scope="src/a.py", witness=_passing_witness(), claim="a-fact"))
    g.publish_knowledge(g.nodes["n1"], _ka(kind=ScopeKind.GLOBAL, scope="", claim="global-fact"))
    c = ContractArtifact(module="m1", symbols=[ContractSymbol(name="f", kind="function")])
    g.register_artifact_contract(c)
    g.subscribe_artifact_contract(c.contract_id, "n1")
    g.save_state()
    raw = json.loads(state_file.read_text())
    assert "knowledge_artifacts" in raw and "artifact_contracts" in raw

    g2 = DAFG.load_state(state_file)
    assert len(g2.knowledge.artifacts) == 2
    by_claim = {a.claim: a for a in g2.knowledge.artifacts.values()}
    assert by_claim["a-fact"].state == ArtifactState.WITNESS_CHECKED
    assert by_claim["global-fact"].state == ArtifactState.UNCHECKED
    assert g2.artifact_contracts[c.contract_id].consumers == {"n1"}
    assert g2.artifact_contracts[c.contract_id].revision == 1
    got = g2.deliver_knowledge(g2.nodes["n1"])
    assert {a.claim for a in got} == {"a-fact", "global-fact"}


# --- protocol actions --------------------------------------------------------


def test_publish_knowledge_action_publishes_and_flag_refutes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = DAFG(nodes={"n1": _node()})
    art = _ka(scope="src/a.py", witness=_passing_witness(), claim="a-fact").to_dict()
    cmd = ProtocolCommand(
        idempotency_key="pk1",
        action=Action.PUBLISH_KNOWLEDGE,
        node_id="n1",
        run_id=g.run_id,
        payload={"artifact": art, "workdir": str(tmp_path)},
    )
    events, audit = ProtocolEngine.decide(g, cmd, g.next_seq)
    assert audit is None and len(events) == 1
    from dafg.protocol import ProtocolReducer
    ProtocolReducer.apply(g, events[0])
    assert len(g.knowledge.deliver(ScopeKind.FILE, "src/a.py")) == 1

    # Now flag it with a failing witness -> refuted, excluded.
    stored = g.knowledge.deliver(ScopeKind.FILE, "src/a.py")[0]
    stored.witness = _failing_witness()
    flag_cmd = ProtocolCommand(
        idempotency_key="fk1",
        action=Action.FLAG_KNOWLEDGE,
        node_id="n1",
        run_id=g.run_id,
        reason="looks stale",
        payload={"artifact": stored.to_dict(), "workdir": str(tmp_path)},
    )
    events, audit = ProtocolEngine.decide(g, flag_cmd, g.next_seq)
    assert audit is None
    ProtocolReducer.apply(g, events[0])
    assert stored.state == ArtifactState.REFUTED
    assert g.knowledge.deliver(ScopeKind.FILE, "src/a.py") == []


def test_publish_knowledge_action_rejects_wrong_producer():
    g = DAFG(nodes={"n1": _node()})
    art = _ka(scope="src/a.py").to_dict()
    art["producer"] = "n2"
    cmd = ProtocolCommand(
        idempotency_key="pk-bad",
        action=Action.PUBLISH_KNOWLEDGE,
        node_id="n1",
        run_id=g.run_id,
        payload={"artifact": art},
    )
    events, audit = ProtocolEngine.decide(g, cmd, g.next_seq)
    assert events == [] and audit is not None
    assert "producer" in audit.reason


def test_publish_knowledge_action_rejects_out_of_scope():
    g = DAFG(nodes={"n1": _node(owns=("src/a.py",))})
    art = _ka(scope="elsewhere/b.py").to_dict()
    cmd = ProtocolCommand(
        idempotency_key="pk-scope",
        action=Action.PUBLISH_KNOWLEDGE,
        node_id="n1",
        run_id=g.run_id,
        payload={"artifact": art},
    )
    events, audit = ProtocolEngine.decide(g, cmd, g.next_seq)
    assert events == [] and audit is not None
    assert "OWNS" in audit.reason


def test_knowledge_actions_do_not_change_protocol_state():
    g = DAFG(nodes={"n1": _node()})
    from dafg.protocol import ProtocolState
    g.nodes["n1"].protocol_state = ProtocolState.PROVING
    art = _ka(scope="src/a.py").to_dict()
    cmd = ProtocolCommand(
        idempotency_key="pk-state",
        action=Action.PUBLISH_KNOWLEDGE,
        node_id="n1",
        run_id=g.run_id,
        payload={"artifact": art},
    )
    events, audit = ProtocolEngine.decide(g, cmd, g.next_seq)
    assert audit is None
    assert events[0].to_state == ProtocolState.PROVING.value
