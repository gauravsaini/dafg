"""AECP Artifact-Exclusive Communication Protocol for DAFG.

Multi-agent coordination in DAFG is already indirect: agents never message each
other; everything flows through the runtime (harness). This module makes that
explicit and complete, following the AECP protocol (arXiv 2610.06481):

- KnowledgeArtifact: a claim tied to a scope (symbol/file/directory/global)
  with an optional executable witness. The harness runs the witness at
  publication, delivers non-refuted findings at scope-access (when an agent
  touches matching code), and lets consumers flag claims for re-verification.
- ContractArtifact: symbol-level interface commitments with revision
  tracking. A revision marks registered consumers stale until they
  acknowledge the new revision.

Only stdlib is used. All imports inside DAFG must be absolute
(``from dafg.artifacts import ...``).
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_scope_path(path: str) -> str:
    """Normalize a scope path for matching (mirror of runtime.paths_overlap)."""
    p = os.path.normpath(path.strip()).replace(chr(92), "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _path_is_under(child: str, parent: str) -> bool:
    child_n = _normalize_scope_path(child)
    parent_n = _normalize_scope_path(parent)
    return child_n == parent_n or child_n.startswith(parent_n + "/")


class ScopeKind(str, Enum):
    """Granularity of a knowledge artifact's applicable scope."""
    SYMBOL = "SYMBOL"
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    GLOBAL = "GLOBAL"


class ArtifactState(str, Enum):
    """Harness-maintained verification state of a knowledge artifact."""
    UNCHECKED = "UNCHECKED"
    WITNESS_CHECKED = "WITNESS_CHECKED"
    REFUTED = "REFUTED"


class WitnessRejectedError(ValueError):
    """Raised when a witness is malformed (publication rejected)."""


class WitnessRefutedError(WitnessRejectedError):
    """Raised when a witness refutes its claim (publication rejected, claim REFUTED)."""


def _validate_witness(witness: Any) -> Tuple[List[str], str, int]:
    """Validate witness shape; return (command, marker, timeout_s).

    Raises WitnessRejectedError when the witness is malformed.
    """
    if not isinstance(witness, dict):
        raise WitnessRejectedError(f"Witness must be a dict, got {type(witness).__name__}")
    command = witness.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        raise WitnessRejectedError("Witness 'command' must be a non-empty argv list of strings")
    marker = witness.get("marker", "")
    if not isinstance(marker, str) or not marker:
        raise WitnessRejectedError("Witness 'marker' must be a non-empty string")
    timeout_s = witness.get("timeout_s", 30)
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
        raise WitnessRejectedError("Witness 'timeout_s' must be a positive int")
    return command, marker, timeout_s


def run_witness(witness: Dict[str, Any], workdir: str) -> Tuple[bool, str]:
    """Run a validated witness subprocess.

    Success = exit code 0 AND marker present in stdout. Returns
    (passed, stdout_excerpt). Any subprocess failure (non-zero exit,
    timeout, missing binary) is a witness failure, not a malformed witness.
    """
    command, marker, timeout_s = _validate_witness(witness)
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=workdir,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return False, out[:2000]
    except OSError:
        return False, ""
    stdout = proc.stdout or ""
    return (proc.returncode == 0 and marker in stdout), stdout[:2000]


@dataclass
class KnowledgeArtifact:
    """A scope-linked finding with an executable witness and harness state.

    Fields map to AECP's <c, s, e, z>: claim=c, (scope_kind, scope)=s,
    witness=e, state=z (harness-maintained).
    """
    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    claim: str = ""
    scope_kind: ScopeKind = ScopeKind.GLOBAL
    scope: str = ""
    witness: Optional[Dict[str, Any]] = None
    state: ArtifactState = ArtifactState.UNCHECKED
    producer: str = ""
    created_at: str = field(default_factory=_utcnow)
    revision: int = 1
    audit: List[str] = field(default_factory=list)

    def matches_query(self, query_kind: ScopeKind, query_scope: str) -> bool:
        """Scope matching rule (enclosing-directory fallback like AECP).

        SYMBOL matches the same symbol; FILE the same file; DIRECTORY matches
        a file (or directory) under it; GLOBAL matches everything.
        """
        if self.scope_kind == ScopeKind.GLOBAL:
            return True
        if self.scope_kind == ScopeKind.SYMBOL:
            return query_kind == ScopeKind.SYMBOL and self.scope == query_scope
        if self.scope_kind == ScopeKind.FILE:
            return (
                query_kind == ScopeKind.FILE
                and _normalize_scope_path(self.scope) == _normalize_scope_path(query_scope)
            )
        if self.scope_kind == ScopeKind.DIRECTORY:
            return query_kind in (ScopeKind.FILE, ScopeKind.DIRECTORY) and _path_is_under(
                query_scope, self.scope
            )
        return False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scope_kind"] = self.scope_kind.value if isinstance(self.scope_kind, ScopeKind) else self.scope_kind
        d["state"] = self.state.value if isinstance(self.state, ArtifactState) else self.state
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeArtifact":
        d = dict(data)
        if "scope_kind" in d and isinstance(d["scope_kind"], str):
            d["scope_kind"] = ScopeKind(d["scope_kind"])
        if "state" in d and isinstance(d["state"], str):
            d["state"] = ArtifactState(d["state"])
        d.setdefault("artifact_id", uuid.uuid4().hex)
        d.setdefault("created_at", _utcnow())
        d.setdefault("audit", [])
        return cls(**d)


class ArtifactStore:
    """Harness-side store for knowledge artifacts.

    Rules (AECP):
    - publish: run attached witness; reject publication when the witness is
      malformed; mark REFUTED and reject when the witness refutes the claim;
      otherwise store as WITNESS_CHECKED (or UNCHECKED without witness).
    - deliver: scope-triggered retrieval; refuted artifacts are excluded.
    - flag: a consumer flags a claim; the harness reruns the witness, refutes
      and excludes on failure, and keeps an audit record either way.
    """

    def __init__(self) -> None:
        self.artifacts: Dict[str, KnowledgeArtifact] = {}
        self.audit: List[str] = []

    def _log(self, event: str) -> None:
        self.audit.append(f"{_utcnow()} {event}")

    def publish(self, artifact: KnowledgeArtifact, workdir: str) -> KnowledgeArtifact:
        """Publish a knowledge artifact, running its witness if attached.

        Raises WitnessRejectedError (malformed witness) or WitnessRefutedError
        (witness refutes the claim); the artifact object is left in the
        corresponding state (UNCHECKED / REFUTED) and an audit record is kept.
        """
        artifact.audit.append(f"{_utcnow()} publish attempt by '{artifact.producer}'")
        if artifact.witness is not None:
            passed, _ = run_witness(artifact.witness, workdir)
            if passed:
                artifact.state = ArtifactState.WITNESS_CHECKED
                artifact.audit.append(f"{_utcnow()} witness passed")
                self._log(f"published {artifact.artifact_id} WITNESS_CHECKED scope={artifact.scope_kind.value}:{artifact.scope}")
            else:
                artifact.state = ArtifactState.REFUTED
                artifact.audit.append(f"{_utcnow()} witness refuted claim; publication rejected")
                self._log(f"rejected {artifact.artifact_id}: witness refuted claim")
                raise WitnessRefutedError(
                    f"Witness refuted claim for artifact {artifact.artifact_id}; publication rejected"
                )
        else:
            artifact.state = ArtifactState.UNCHECKED
            artifact.audit.append(f"{_utcnow()} no witness; stored UNCHECKED")
            self._log(f"published {artifact.artifact_id} UNCHECKED scope={artifact.scope_kind.value}:{artifact.scope}")
        self.artifacts[artifact.artifact_id] = artifact
        return artifact

    def deliver(self, scope_kind: ScopeKind, scope: str) -> List[KnowledgeArtifact]:
        """Return non-refuted artifacts matching the query scope."""
        return [
            a
            for a in self.artifacts.values()
            if a.state != ArtifactState.REFUTED and a.matches_query(scope_kind, scope)
        ]

    def flag(self, artifact_id: str, reason: str, workdir: str) -> KnowledgeArtifact:
        """Consumer flags a claim; rerun witness, refute+exclude on failure."""
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise KeyError(f"Unknown artifact '{artifact_id}'")
        artifact.audit.append(f"{_utcnow()} flagged: {reason}")
        self._log(f"flagged {artifact_id}: {reason}")
        if artifact.witness is not None:
            passed, _ = run_witness(artifact.witness, workdir)
            if not passed:
                artifact.state = ArtifactState.REFUTED
                artifact.audit.append(f"{_utcnow()} witness rerun refuted claim; excluded from delivery")
                self._log(f"refuted {artifact_id} on flag rerun; excluded from delivery")
            else:
                artifact.audit.append(f"{_utcnow()} witness rerun passed; claim stands")
                self._log(f"flag rerun passed for {artifact_id}; claim stands")
        else:
            artifact.audit.append(f"{_utcnow()} no witness to rerun; claim stands UNCHECKED")
        return artifact

    def history(self) -> List[str]:
        """Audit trail of store-level events."""
        return list(self.audit)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifacts": {aid: a.to_dict() for aid, a in self.artifacts.items()},
            "audit": list(self.audit),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactStore":
        store = cls()
        for aid, adata in (data.get("artifacts") or {}).items():
            store.artifacts[aid] = KnowledgeArtifact.from_dict(adata)
        store.audit = list(data.get("audit") or [])
        return store


@dataclass
class ContractSymbol:
    """One declared symbol in a contract artifact."""
    name: str
    kind: str  # e.g. "function", "class", "endpoint", "schema"
    signature: str = ""
    semantics: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContractSymbol":
        return cls(**data)


@dataclass
class ContractArtifact:
    """AECP ContractArtifact: symbol-level interface commitments with revisions.

    Consumers register on the contract; ``revise()`` bumps the revision and
    marks all registered consumers stale. ``acknowledge()`` clears a
    consumer's stale mark once it has re-read the current revision.
    """
    contract_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    module: str = ""
    symbols: List[ContractSymbol] = field(default_factory=list)
    purpose: str = ""
    dependencies: List[str] = field(default_factory=list)
    revision: int = 1
    consumers: Set[str] = field(default_factory=set)
    stale_consumers: Set[str] = field(default_factory=set)
    audit: List[str] = field(default_factory=list)

    def register_consumer(self, consumer_id: str) -> None:
        self.consumers.add(consumer_id)
        self.stale_consumers.discard(consumer_id)
        self.audit.append(f"{_utcnow()} consumer registered: {consumer_id}")

    def revise(
        self,
        symbols: Optional[List[ContractSymbol]] = None,
        purpose: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        reason: str = "",
    ) -> Set[str]:
        """Bump revision; mark all registered consumers stale.

        Returns the affected (now stale) consumers.
        """
        if symbols is not None:
            self.symbols = symbols
        if purpose is not None:
            self.purpose = purpose
        if dependencies is not None:
            self.dependencies = dependencies
        self.revision += 1
        affected = set(self.consumers)
        self.stale_consumers.update(affected)
        self.audit.append(
            f"{_utcnow()} revised to v{self.revision} ({reason or 'no reason'}); stale: {sorted(affected)}"
        )
        return affected

    def acknowledge(self, consumer_id: str) -> None:
        """Consumer has re-read the current revision; clear its stale mark."""
        self.stale_consumers.discard(consumer_id)
        self.audit.append(f"{_utcnow()} consumer acknowledged v{self.revision}: {consumer_id}")

    def is_stale(self, consumer_id: str) -> bool:
        return consumer_id in self.stale_consumers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "module": self.module,
            "symbols": [s.to_dict() for s in self.symbols],
            "purpose": self.purpose,
            "dependencies": list(self.dependencies),
            "revision": self.revision,
            "consumers": sorted(self.consumers),
            "stale_consumers": sorted(self.stale_consumers),
            "audit": list(self.audit),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContractArtifact":
        d = dict(data)
        symbols = [ContractSymbol.from_dict(s) for s in (d.get("symbols") or [])]
        return cls(
            contract_id=d.get("contract_id") or uuid.uuid4().hex,
            module=d.get("module", ""),
            symbols=symbols,
            purpose=d.get("purpose", ""),
            dependencies=list(d.get("dependencies") or []),
            revision=int(d.get("revision", 1)),
            consumers=set(d.get("consumers") or []),
            stale_consumers=set(d.get("stale_consumers") or []),
            audit=list(d.get("audit") or []),
        )
