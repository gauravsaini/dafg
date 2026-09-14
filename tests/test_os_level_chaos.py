"""Real OS-Level Chaos and Concurrency Tests.

Directly exercises:
1. Real OS-level process interruption via kill -9 (signal.SIGKILL) against an
   in-flight subprocess, followed by clean orchestrator recovery (epoch bump,
   physical attempts incremented, revisions preserved, stale worker fenced).
2. Real concurrent multi-process OS race (multiprocessing.Process) on state.json,
   verifying kernel-level fcntl.flock advisory locking, optimistic concurrency
   conflict detection, and automated state reconciliation without lost updates.
"""

import json
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import pytest

from dafg.runtime import DAFG, StateStore, OptimisticConcurrencyConflictError, TaskNode, NodeStatus
from dafg.protocol import Action, DispatchIdentity, ProtocolCommand, ProtocolState, StaleDispatchError


# ---------------------------------------------------------------------------
# Multiprocessing Worker for Vector #6 (Real OS Processes Racing on state.json)
# ---------------------------------------------------------------------------

def _os_process_worker(state_path_str: str, worker_id: int):
    """Executed in an independent OS process to race on state.json."""
    from dafg.runtime import DAFG, TaskNode
    state_path = Path(state_path_str)
    # Stagger entry slightly to produce real-world interleaved CAS races
    time.sleep(0.005 * (worker_id % 3))
    graph = DAFG.load_state(state_path)
    # Each process adds its own task node
    node_id = f"proc_node_{worker_id}"
    graph.nodes[node_id] = TaskNode(id=node_id, title=f"Node from OS PID {os.getpid()}")
    # save_state performs CAS commit with automated conflict retry and reconciliation
    graph.save_state()


def test_real_os_multiprocess_cas_race(tmp_path):
    """Test #6: Real independent OS processes concurrently modifying state.json."""
    state_file = tmp_path / "shared_state.json"
    initial_graph = DAFG(
        nodes={"init_node": TaskNode(id="init_node", title="Initial Task")},
        state_path=state_file,
    )
    assert initial_graph.state_version == 1

    num_processes = 8
    processes = []
    for i in range(num_processes):
        p = mp.Process(target=_os_process_worker, args=(str(state_file), i))
        processes.append(p)

    # Launch all OS processes simultaneously
    for p in processes:
        p.start()

    # Wait for all processes to complete
    for p in processes:
        p.join(timeout=10.0)
        assert p.exitcode == 0, f"Process {p.pid} failed with exitcode {p.exitcode}"

    # Load canonical state and verify zero lost updates
    final_data = StateStore.load(state_file)
    assert final_data["state_version"] >= 1 + num_processes

    # All nodes from all independent OS processes must be preserved
    nodes = final_data.get("nodes", {})
    assert "init_node" in nodes
    for i in range(num_processes):
        assert f"proc_node_{i}" in nodes, f"Lost update: proc_node_{i} missing from canonical state"


# ---------------------------------------------------------------------------
# Real OS Process Interruption for Vector #2 (kill -9 live process)
# ---------------------------------------------------------------------------

def test_real_os_subprocess_kill_9_interruption_and_recovery(tmp_path):
    """Test #2: Subprocess terminated via kill -9 (SIGKILL) mid-execution."""
    state_file = tmp_path / "interrupted_state.json"
    ready_file = tmp_path / "worker_ready.flag"

    # Inline script run by independent OS process
    worker_script = f"""
import json, os, time, sys
from pathlib import Path
from dafg.runtime import DAFG, TaskNode, NodeStatus
from dafg.protocol import DispatchIdentity, ProtocolState

state_path = Path(r"{state_file}")
ready_path = Path(r"{ready_file}")

node = TaskNode(
    id="interrupted_task",
    title="In flight long task",
    status=NodeStatus.RUNNING,
)
node.protocol_state = ProtocolState.VERIFYING
node.epoch = 1
node.active_dispatch = DispatchIdentity(
    run_id="run_live_interruption",
    node_id="interrupted_task",
    epoch=1,
    attempt_id=1,
    context_snapshot_id="snap_v1",
    contract_version=1,
)

graph = DAFG(nodes={{"interrupted_task": node}}, state_path=state_path)
graph.run_id = "run_live_interruption"
graph.run_epoch = 1
graph.save_state()

# Signal parent that state.json is written with RUNNING node
ready_path.write_text("READY")

# Sleep to simulate in-flight execution until SIGKILL arrives
time.sleep(30)
"""
    script_file = tmp_path / "worker.py"
    script_file.write_text(worker_script, encoding="utf-8")

    # Spawn separate OS process
    proc = subprocess.Popen(
        [sys.executable, str(script_file)],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait until worker writes the in-flight state
    deadline = time.time() + 5.0
    while not ready_file.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert ready_file.exists(), "Worker process failed to start in time"

    # Verify state.json was written with RUNNING node by the child process
    initial_data = StateStore.load(state_file)
    assert initial_data["nodes"]["interrupted_task"]["status"] == "RUNNING"
    assert proc.poll() is None, "Worker process terminated prematurely"

    # Send hard SIGKILL (kill -9) directly to the OS process
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5.0)

    # Verify process terminated by SIGKILL (-9 on POSIX, 137 exit code)
    assert proc.returncode in (-signal.SIGKILL, 137)

    # Now resume in a fresh orchestrator process
    resumed = DAFG.load_state(state_file)

    # 1. Run epoch bumped from 1 to 2
    assert resumed.run_epoch == 2

    # 2. Interrupted node reset to PENDING with attempt incremented
    rec_node = resumed.nodes["interrupted_task"]
    assert rec_node.status == NodeStatus.PENDING
    assert rec_node.epoch == 2
    assert rec_node.attempts == 1
    assert rec_node.revisions == 0
    assert rec_node.active_dispatch is None

    # 3. Interruption recovery event logged
    assert any(e.get("type") == "RECOVERED_FROM_INTERRUPTION" for e in resumed.domain_events)

    # 4. Delayed commit from dead epoch-1 worker is strictly blocked by dispatch identity fencing
    stale_cmd = ProtocolCommand(
        idempotency_key="delayed_commit_from_killed_worker",
        action=Action.ACCEPT_VERDICT,
        node_id="interrupted_task",
        run_id="run_live_interruption",
        dispatch_identity=DispatchIdentity(
            run_id="run_live_interruption",
            node_id="interrupted_task",
            epoch=1,
            attempt_id=1,
            context_snapshot_id="snap_v1",
            contract_version=1,
        ),
        payload={"result": {"success": True}},
    )
    with pytest.raises(StaleDispatchError) as exc_info:
        resumed.submit_command(stale_cmd)
    assert "Stale dispatch identity" in str(exc_info.value)
