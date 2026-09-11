"""DAFG Dynamic Task Graph & Depth Tree Runtime.

Executes autonomous agent workflows backed by objective gate evidence, dynamic
planning, specialist roles, dependency expansion (`needs`), depth trees,
disjoint file ownership (`OWNS:`), rolling waves, budget caps, and atomic state
persistence (`state.json`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import fnmatch
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dafg.gates import Gate, GateEngine, GateLedger, GateResult


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class Role(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    SPECIALIST = "specialist"


class BudgetExceededError(Exception):
    """Raised when a resource budget cap is exceeded."""
    pass


@dataclass
class Budget:
    max_calls: int = 50
    max_nodes: int = 20
    max_revisions: int = 3
    deadline: Optional[float] = None  # Unix timestamp

    calls_consumed: int = 0
    nodes_created: int = 0
    revisions_consumed: int = 0

    def check_call(self) -> None:
        if self.calls_consumed >= self.max_calls:
            raise BudgetExceededError(
                f"Model call budget exceeded: {self.calls_consumed}/{self.max_calls}"
            )
        self.calls_consumed += 1

    def check_node(self) -> None:
        if self.nodes_created >= self.max_nodes:
            raise BudgetExceededError(
                f"Node budget exceeded: {self.nodes_created}/{self.max_nodes}"
            )
        self.nodes_created += 1

    def check_deadline(self) -> None:
        if self.deadline is not None and time.time() > self.deadline:
            raise BudgetExceededError(
                f"Deadline exceeded: {time.time():.1f} > {self.deadline:.1f}"
            )

    def check_revision(self) -> None:
        if self.revisions_consumed >= self.max_revisions:
            raise BudgetExceededError(
                f"Revision budget exceeded: {self.revisions_consumed}/{self.max_revisions}"
            )
        self.revisions_consumed += 1


@dataclass
class TaskNode:
    id: str
    title: str
    role: str = "coder"
    status: NodeStatus = NodeStatus.PENDING
    needs: List[str] = field(default_factory=list)  # prerequisite node IDs
    assigned_gates: List[str] = field(default_factory=list)  # gate IDs in GATES.md
    owns: List[str] = field(default_factory=list)  # declared file paths / patterns
    parent_id: Optional[str] = None  # parent in depth tree
    children: List[str] = field(default_factory=list)  # child node IDs
    depth: int = 0
    revisions: int = 0
    max_revisions: int = 3
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    persona: Optional[Dict[str, Any]] = None
    persona_history: List[Dict[str, Any]] = field(default_factory=list)
    backend_name: Optional[str] = None
    persona_switches: int = 0
    max_persona_switches: int = 2

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, NodeStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskNode:
        d = data.copy()
        if "status" in d and isinstance(d["status"], str):
            d["status"] = NodeStatus(d["status"])
        return cls(**d)


@dataclass
class AgentResponse:
    """Output returned by specialist agents / LLMs."""
    output: str = ""
    status: str = "COMPLETED"
    needs: List[Union[str, TaskNode, Dict[str, Any]]] = field(default_factory=list)
    spawn_children: List[Union[TaskNode, Dict[str, Any]]] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "status": self.status,
            "files_modified": self.files_modified,
            "metadata": self.metadata,
        }


def paths_overlap(path1: str, path2: str) -> bool:
    """Check if two file ownership paths or globs overlap."""
    p1 = os.path.normpath(path1.strip()).replace("\\", "/")
    p2 = os.path.normpath(path2.strip()).replace("\\", "/")
    if p1.startswith("./"):
        p1 = p1[2:]
    if p2.startswith("./"):
        p2 = p2[2:]

    if p1 == p2:
        return True
    if p1 == "." or p2 == ".":
        return True
    if fnmatch.fnmatch(p1, p2) or fnmatch.fnmatch(p2, p1):
        return True
    # Directory prefix containment: e.g. "src/db" overlaps with "src/db/models.py"
    if p2.startswith(f"{p1}/") or p1.startswith(f"{p2}/"):
        return True
    return False


def nodes_conflict(node1: TaskNode, node2: TaskNode, ledger: Optional[GateLedger] = None) -> bool:
    """Check if two nodes have overlapping file ownership."""
    def get_owns(n: TaskNode) -> Set[str]:
        res = set(n.owns)
        if ledger and n.assigned_gates:
            for gid in n.assigned_gates:
                g = ledger.get_gate(gid)
                if g and g.owns:
                    for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                        res.add(p)
        return res

    owns1 = get_owns(node1)
    owns2 = get_owns(node2)
    for p1 in owns1:
        for p2 in owns2:
            if paths_overlap(p1, p2):
                return True
    return False


class StateStore:
    """Handles atomic persistence of DAFG runtime state."""

    @staticmethod
    def save(state: Dict[str, Any], filepath: Union[str, Path]) -> None:
        fp = Path(filepath)
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = fp.with_name(f"{fp.name}.tmp.{os.getpid()}")
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp_file, fp)

    @staticmethod
    def load(filepath: Union[str, Path]) -> Dict[str, Any]:
        fp = Path(filepath)
        return json.loads(fp.read_text(encoding="utf-8"))


class DAFG:
    """Dynamic Agent Feedback Graph Runtime."""

    def __init__(
        self,
        nodes: Optional[Dict[str, TaskNode]] = None,
        budget: Optional[Budget] = None,
        ledger: Optional[GateLedger] = None,
        engine: Optional[GateEngine] = None,
        state_path: Optional[Union[str, Path]] = None,
        router: Optional[Any] = None,
        compiler: Optional[Any] = None,
        policy: Optional[Any] = None,
        switcher: Optional[Any] = None,
        classifier: Optional[Any] = None,
    ):
        self.nodes: Dict[str, TaskNode] = {}
        self.budget: Budget = budget or Budget()
        self.ledger: Optional[GateLedger] = ledger
        self.engine: Optional[GateEngine] = engine
        self.state_path: Optional[Path] = Path(state_path) if state_path else None
        self.router: Optional[Any] = router
        self.compiler: Optional[Any] = compiler
        self.policy: Optional[Any] = policy
        self.switcher: Optional[Any] = switcher
        self.classifier: Optional[Any] = classifier
        self.execution_history: List[Dict[str, Any]] = []
        self.gate_states: Dict[str, Any] = {}

        if nodes:
            for node in nodes.values():
                self.add_node(node, track_budget=False)

    def add_node(self, node: TaskNode, track_budget: bool = True) -> TaskNode:
        if node.parent_id == node.id:
            node.parent_id = None

        is_new = node.id not in self.nodes
        if track_budget and is_new:
            self.budget.check_node()
        self.nodes[node.id] = node

        # Inherit declared ownership from assigned gates in ledger
        if self.ledger and node.assigned_gates:
            for gid in node.assigned_gates:
                g = self.ledger.get_gate(gid)
                if g and g.owns:
                    for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                        if p not in node.owns:
                            node.owns.append(p)

        # Parent linkage
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            if node.id not in parent.children:
                parent.children.append(node.id)
            node.depth = parent.depth + 1

        # Reverse parent linkage: existing nodes might be children of this node
        for existing in self.nodes.values():
            if existing.parent_id == node.id:
                if existing.id not in node.children:
                    node.children.append(existing.id)
                existing.depth = node.depth + 1

        self.save_state()
        return node

    def init_from_ledger(self) -> List[TaskNode]:
        """Initialize task nodes from ledger gates if graph has no nodes."""
        if not self.ledger:
            return []
        created = []
        for gid, gate in self.ledger.gates.items():
            if gate.status == "ABANDONED":
                continue
            nid = f"task_{gid}"
            if nid not in self.nodes:
                owns = [p.strip() for p in gate.owns.split(",") if p.strip()] if gate.owns else []
                node = TaskNode(
                    id=nid,
                    title=f"Complete gate {gid}: {gate.title}",
                    assigned_gates=[gid],
                    owns=owns,
                )
                self.add_node(node)
                created.append(node)
        return created

    def get_ready_nodes(self) -> List[TaskNode]:
        """Nodes eligible for execution: status is PENDING, READY, REJECTED, or BLOCKED,
        and all needs and children prerequisites are satisfied."""
        ready: List[TaskNode] = []
        for node in self.nodes.values():
            if node.status in (NodeStatus.PENDING, NodeStatus.READY, NodeStatus.REJECTED, NodeStatus.BLOCKED):
                deps_met = True
                for dep_id in node.needs:
                    dep = self.nodes.get(dep_id)
                    if not dep or dep.status != NodeStatus.ACCEPTED:
                        deps_met = False
                        break
                if not deps_met:
                    continue

                # Depth tree parent blocking: if node has children, it cannot run until all children are ACCEPTED
                if node.children:
                    children_met = all(
                        self.nodes.get(cid) is not None and self.nodes[cid].status == NodeStatus.ACCEPTED
                        for cid in node.children
                    )
                    if not children_met:
                        continue

                ready.append(node)
        return ready

    def compute_waves(self, ready_nodes: List[TaskNode]) -> List[List[TaskNode]]:
        """Partition ready nodes into rolling execution waves with disjoint OWNS."""
        waves: List[List[TaskNode]] = []
        for candidate in ready_nodes:
            placed = False
            for wave in waves:
                conflict = any(nodes_conflict(candidate, member, ledger=self.ledger) for member in wave)
                if not conflict:
                    wave.append(candidate)
                    placed = True
                    break
            if not placed:
                waves.append([candidate])
        return waves

    def execute_node(
        self,
        node: TaskNode,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> bool:
        """Execute a single task node.
        
        Returns True if node reached ACCEPTED status, False otherwise.
        """
        self.budget.check_call()
        self.budget.check_deadline()

        node.status = NodeStatus.RUNNING
        self.save_state()

        # Run agent executor
        context = {
            "graph": self,
            "ledger": self.ledger,
            "budget": self.budget,
            "depth": node.depth,
        }

        # 0. Persona Compilation & Capability-Aware Routing
        if self.compiler and node.persona is None:
            compiled = self.compiler.compile(node, context=context, attempt=node.revisions + 1)
            node.persona = compiled.to_dict()

        if self.router and node.persona:
            from dafg.persona import PersonaProfile
            profile = PersonaProfile.from_dict(node.persona)
            dispatch_plan = self.router.dispatch(node, profile, context=context, budget=self.budget)
            node.backend_name = dispatch_plan.backend.name
            context.update(dispatch_plan.scoped_context)

        response: AgentResponse
        try:
            try:
                if executor_fn:
                    response = executor_fn(node, context)
                else:
                    # Default executor: self-declares completed
                    response = AgentResponse(output="Default execution completed")
            except Exception as e:
                node.revisions += 1
                if self.classifier and self.switcher and node.persona:
                    from dafg.persona import PersonaProfile
                    failure_kind = self.classifier.classify(error_message=str(e))
                    profile = PersonaProfile.from_dict(node.persona)
                    adapted, switched = self.switcher.adapt(node, profile, failure_kind, feedback=str(e))
                    if switched:
                        node.persona_history.append(node.persona)
                        node.persona = adapted.to_dict()
                        self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                if node.revisions >= node.max_revisions:
                    node.status = NodeStatus.FAILED
                else:
                    node.status = NodeStatus.REJECTED
                self._record_event(node, node.status.value, f"Agent execution error: {e}")
                self.save_state()
                self.budget.check_revision()
                return False

            # Check explicit agent failure status
            if response.status in ("FAILED", "ERROR", "REJECTED"):
                node.revisions += 1
                if self.classifier and self.switcher and node.persona:
                    from dafg.persona import PersonaProfile
                    failure_kind = self.classifier.classify(error_message=response.output, feedback=response.output)
                    profile = PersonaProfile.from_dict(node.persona)
                    adapted, switched = self.switcher.adapt(node, profile, failure_kind, feedback=response.output)
                    if switched:
                        node.persona_history.append(node.persona)
                        node.persona = adapted.to_dict()
                        self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                if node.revisions >= node.max_revisions:
                    node.status = NodeStatus.FAILED
                else:
                    node.status = NodeStatus.REJECTED
                self._record_event(node, node.status.value, f"Agent returned failure status '{response.status}': {response.output}")
                self.save_state()
                self.budget.check_revision()
                return False

            # 1. Dynamic Planning & Dependency Expansion (`needs`)
            if response.needs:
                for need in response.needs:
                    need_id: str
                    if isinstance(need, str):
                        need_id = need
                    elif isinstance(need, TaskNode):
                        self.add_node(need)
                        need_id = need.id
                    elif isinstance(need, dict):
                        new_node = TaskNode.from_dict(need)
                        self.add_node(new_node)
                        need_id = new_node.id
                    else:
                        continue

                    if need_id != node.id and need_id not in node.needs:
                        node.needs.append(need_id)

                # Check if any dependencies are still pending
                unmet_deps = [d for d in node.needs if self.nodes.get(d) is None or self.nodes[d].status != NodeStatus.ACCEPTED]
                if unmet_deps:
                    node.status = NodeStatus.BLOCKED
                    self._record_event(node, "BLOCKED", f"Dynamic dependencies added: {unmet_deps}")
                    self.save_state()
                    return False

            # 2. Depth Tree Decomposition (spawn_children)
            if response.spawn_children:
                for child_def in response.spawn_children:
                    child_node: TaskNode
                    if isinstance(child_def, TaskNode):
                        child_node = child_def
                    elif isinstance(child_def, dict):
                        child_node = TaskNode.from_dict(child_def)
                    else:
                        continue

                    if child_node.id == node.id:
                        continue

                    child_node.parent_id = node.id
                    child_node.depth = node.depth + 1
                    self.add_node(child_node)

                # Parent waits for children
                node.status = NodeStatus.BLOCKED
                self._record_event(node, "BLOCKED", f"Spawned children: {node.children}")
                self.save_state()
                return False

            # 3. Objective Gate Verification
            # A node is ONLY accepted when its assigned gates in GATES.md are verified with passing evidence!
            if node.assigned_gates:
                if not self.ledger or not self.engine:
                    node.status = NodeStatus.FAILED
                    self._record_event(node, "FAILED", "No gate engine/ledger configured to verify assigned gates")
                    self.save_state()
                    return False

                all_gates_pass = True
                gate_failures: List[str] = []

                for gid in node.assigned_gates:
                    gate = self.ledger.get_gate(gid)
                    if not gate:
                        all_gates_pass = False
                        gate_failures.append(f"Gate '{gid}' not found in ledger")
                        continue

                    res = self.engine.execute_gate(gate, ledger=self.ledger, reverify=True)
                    if res.status != "MET":
                        all_gates_pass = False
                        gate_failures.append(f"Gate '{gid}' status={res.status} ({res.error or 'failed'})")

                if not all_gates_pass:
                    # Gate failed: reject and track revision
                    node.revisions += 1
                    if self.classifier and self.switcher and node.persona:
                        from dafg.persona import PersonaProfile
                        feedback_str = "; ".join(gate_failures)
                        failure_kind = self.classifier.classify(error_message=feedback_str, gate_failures=gate_failures)
                        profile = PersonaProfile.from_dict(node.persona)
                        adapted, switched = self.switcher.adapt(node, profile, failure_kind, feedback=feedback_str)
                        if switched:
                            node.persona_history.append(node.persona)
                            node.persona = adapted.to_dict()
                            self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                    if node.revisions >= node.max_revisions:
                        node.status = NodeStatus.FAILED
                        self._record_event(node, "FAILED", f"Max revisions reached. Gate failures: {gate_failures}")
                    else:
                        node.status = NodeStatus.REJECTED
                        self._record_event(node, "REJECTED", f"Gate failures: {gate_failures}")
                    self.save_state()
                    self.budget.check_revision()
                    return False

            # 4. Depth Tree Parent Completion Guard: require child and descendant gate reverification
            if node.children:
                # Check all children are ACCEPTED
                unaccepted_children = [cid for cid in node.children if cid not in self.nodes or self.nodes[cid].status != NodeStatus.ACCEPTED]
                if unaccepted_children:
                    node.status = NodeStatus.BLOCKED
                    self._record_event(node, "BLOCKED", f"Waiting for children: {unaccepted_children}")
                    self.save_state()
                    return False

                # Reverification of child and descendant gates before parent completion
                if self.ledger and self.engine:
                    def _get_descendants(parent: TaskNode, visited: Optional[Set[str]] = None) -> List[TaskNode]:
                        if visited is None:
                            visited = set()
                        desc: List[TaskNode] = []
                        for cid in parent.children:
                            if cid in visited:
                                continue
                            visited.add(cid)
                            c = self.nodes.get(cid)
                            if c:
                                desc.append(c)
                                desc.extend(_get_descendants(c, visited))
                        return desc

                    for desc_node in _get_descendants(node):
                        for gid in desc_node.assigned_gates:
                            gate = self.ledger.get_gate(gid)
                            if gate:
                                res = self.engine.execute_gate(gate, ledger=self.ledger, reverify=True)
                                if res.status != "MET":
                                    # Descendant reverification failed! Demote descendant and reject parent
                                    desc_node.status = NodeStatus.REJECTED
                                    node.revisions += 1
                                    if node.revisions >= node.max_revisions:
                                        node.status = NodeStatus.FAILED
                                    else:
                                        node.status = NodeStatus.REJECTED
                                    self._record_event(
                                        node,
                                        node.status.value,
                                        f"Descendant {desc_node.id} gate {gid} reverification failed: {res.error}",
                                    )
                                    self.save_state()
                                    self.budget.check_revision()
                                    return False

            # All objective gate criteria met
            node.status = NodeStatus.ACCEPTED
            node.result = response.to_dict()
            self._record_event(node, "ACCEPTED", "Objective gate checks and child verifications passed")
            self.save_state()
            return True
        except BudgetExceededError:
            if node.status == NodeStatus.RUNNING:
                node.status = NodeStatus.PENDING
                self.save_state()
            raise

    def step(
        self,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> List[TaskNode]:
        """Execute one wave of ready nodes."""
        ready = self.get_ready_nodes()
        if not ready:
            return []

        waves = self.compute_waves(ready)
        current_wave = waves[0]

        executed: List[TaskNode] = []
        for node in current_wave:
            self.execute_node(node, executor_fn=executor_fn)
            executed.append(node)

        return executed

    def run(
        self,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
        max_steps: int = 100,
    ) -> str:
        """Run DAFG until completion, failure, or budget exhaustion."""
        for _ in range(max_steps):
            if self.is_completed():
                return "COMPLETED"
            if self.has_failed():
                return "FAILED"

            try:
                executed = self.step(executor_fn=executor_fn)
            except BudgetExceededError:
                self.save_state()
                return "BUDGET_EXCEEDED"

            if not executed:
                # No ready nodes can execute. Check if blocked or complete
                if self.is_completed():
                    return "COMPLETED"
                return "BLOCKED"

        return "COMPLETED" if self.is_completed() else "BLOCKED"

    def is_completed(self) -> bool:
        """True if all nodes in graph are ACCEPTED."""
        return len(self.nodes) > 0 and all(n.status == NodeStatus.ACCEPTED for n in self.nodes.values())

    def has_failed(self) -> bool:
        """True if any node in graph is FAILED."""
        return any(n.status == NodeStatus.FAILED for n in self.nodes.values())

    def _record_event(self, node: TaskNode, action: str, details: str) -> None:
        self.execution_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": node.id,
            "role": node.role,
            "action": action,
            "details": details,
            "revisions": node.revisions,
        })

    def save_state(self) -> None:
        if not self.state_path:
            return

        gate_states: Dict[str, Any] = {}
        if self.ledger:
            for gid, gate in self.ledger.gates.items():
                gate_states[gid] = {
                    "status": gate.status,
                    "evidence": gate.evidence,
                    "abandon_reason": gate.abandon_reason,
                }
        elif self.gate_states:
            gate_states = dict(self.gate_states)

        state = {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "budget": {
                "max_calls": self.budget.max_calls,
                "max_nodes": self.budget.max_nodes,
                "max_revisions": self.budget.max_revisions,
                "deadline": self.budget.deadline,
                "calls_consumed": self.budget.calls_consumed,
                "nodes_created": self.budget.nodes_created,
                "revisions_consumed": self.budget.revisions_consumed,
            },
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "gate_states": gate_states,
            "execution_history": self.execution_history,
        }
        StateStore.save(state, self.state_path)

    @classmethod
    def load_state(
        cls,
        state_path: Union[str, Path],
        ledger: Optional[GateLedger] = None,
        engine: Optional[GateEngine] = None,
    ) -> DAFG:
        data = StateStore.load(state_path)
        b_data = data.get("budget", {})
        budget = Budget(
            max_calls=b_data.get("max_calls", 50),
            max_nodes=b_data.get("max_nodes", 20),
            max_revisions=b_data.get("max_revisions", 3),
            deadline=b_data.get("deadline"),
            calls_consumed=b_data.get("calls_consumed", 0),
            nodes_created=b_data.get("nodes_created", 0),
            revisions_consumed=b_data.get("revisions_consumed", 0),
        )

        nodes: Dict[str, TaskNode] = {}
        for nid, ndict in data.get("nodes", {}).items():
            node = TaskNode.from_dict(ndict)
            if node.status == NodeStatus.RUNNING:
                node.status = NodeStatus.PENDING
            nodes[nid] = node

        dafg = cls(
            nodes=None,
            budget=budget,
            ledger=ledger,
            engine=engine,
            state_path=state_path,
        )
        dafg.execution_history = list(data.get("execution_history", []))
        dafg.gate_states = dict(data.get("gate_states", {}))

        # Restore gate states into ledger if provided
        if ledger and dafg.gate_states:
            for gid, gst in dafg.gate_states.items():
                if gid in ledger.gates:
                    g = ledger.gates[gid]
                    g.status = gst.get("status", g.status)
                    g.evidence = gst.get("evidence", g.evidence)
                    g.abandon_reason = gst.get("abandon_reason", g.abandon_reason)

        for nid, node in nodes.items():
            dafg.nodes[nid] = node

        # Ensure parent linkage and gate ownerships
        for node in dafg.nodes.values():
            if dafg.ledger and node.assigned_gates:
                for gid in node.assigned_gates:
                    g = dafg.ledger.get_gate(gid)
                    if g and g.owns:
                        for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                            if p not in node.owns:
                                node.owns.append(p)
            if node.parent_id and node.parent_id in dafg.nodes:
                parent = dafg.nodes[node.parent_id]
                if node.id not in parent.children:
                    parent.children.append(node.id)
                node.depth = parent.depth + 1

        dafg.save_state()
        return dafg
