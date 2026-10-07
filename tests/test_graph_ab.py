"""Unit tests for the graph-isolation A/B experiment (src/dafg/graph_ab.py).

Covers the corruption-check logic, marker round-trip, wave partitioning, and
the summarization math. No network, no model calls, deterministic.
"""

from __future__ import annotations

import tempfile
import threading
from collections import Counter
from pathlib import Path

from dafg.graph_ab import (
    LINE_RE,
    NodeSpec,
    build_shape,
    check_file_markers,
    expected_markers,
    summarize_shape,
    topo_order,
    write_markers,
)


def test_line_regex_accepts_wellformed():
    assert LINE_RE.match("[s2_c1:3]")
    assert LINE_RE.match("[abc_123:0]")
    assert not LINE_RE.match("[s2_c1:3")
    assert not LINE_RE.match("[s2_c1:3[s2_c2:5]")
    assert not LINE_RE.match("]")


def test_write_markers_roundtrip_clean():
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        n = write_markers(workdir, "s1_n1", "s1/s1_n1.txt", 5)
        assert n == 5
        want = Counter({("s1_n1", i): 1 for i in range(5)})
        assert check_file_markers(workdir / "s1/s1_n1.txt", want) == []


def test_check_file_missing():
    with tempfile.TemporaryDirectory() as tmp:
        got = check_file_markers(Path(tmp) / "nope.txt", Counter({("a", 0): 1}))
        assert len(got) == 1 and "missing" in got[0]


def test_check_file_partial_line_is_corruption():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "f.txt"
        p.write_text("[s2_c1:0]\n[s2_c1:1[s2_c2:0]\n]\n")
        want = Counter({("s2_c1", 0): 1, ("s2_c1", 1): 1, ("s2_c2", 0): 1})
        got = check_file_markers(p, want)
        assert any("malformed" in g for g in got)


def test_check_file_content_mismatch():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "f.txt"
        p.write_text("[s2_c1:0]\n")
        want = Counter({("s2_c1", 0): 1, ("s2_c1", 1): 1})
        got = check_file_markers(p, want)
        assert any("mismatch" in g for g in got)


def test_write_markers_honors_stop():
    stop = threading.Event()
    stop.set()
    with tempfile.TemporaryDirectory() as tmp:
        n = write_markers(Path(tmp), "x", "x.txt", 5, stop=stop)
        assert n == 0


def test_expected_markers_union_over_shared_file():
    specs = build_shape("shape2_conflict")
    exp = expected_markers(specs)
    assert sum(exp["s2/shared.txt"].values()) == 16  # 8 from c1 + 8 from c2
    assert sum(exp["s2/c3.txt"].values()) == 8


def test_topo_order_respects_needs():
    specs = build_shape("shape1_fanout")
    order = [s.id for s in topo_order(specs)]
    for s in specs:
        for dep in s.needs:
            assert order.index(dep) < order.index(s.id)


def test_wave_partition_defers_conflicting_node():
    # Real DAFG.compute_waves must serialize the two shared.txt claimants.
    from dafg.runtime import DAFG, NodeStatus, TaskNode

    g = DAFG()
    for s in build_shape("shape2_conflict"):
        n = TaskNode(id=s.id, title=s.id, owns=list(s.owns), needs=list(s.needs))
        n.status = NodeStatus.READY
        g.add_node(n, track_budget=False)
    waves = g.compute_waves(g.get_ready_nodes())
    wave0 = [n.id for n in waves[0]]
    assert not ({"s2_c1", "s2_c2"} <= set(wave0)), "conflicting nodes must not share a wave"
    assert sum(len(d.conflict_reasons) for d in g.wave_diagnostics) >= 1


def test_summarize_math():
    from dafg.graph_ab import TrialResult

    rs = [
        TrialResult(shape="shape1_fanout", mode="G-dafg-graph", rep=i, wall_s=0.4,
                    waves_used=2, deferrals=0, corruption_files=0, corruption_incidents=0,
                    files_checked=6, starved=0, hangs=0, completed_nodes=6, total_nodes=6)
        for i in range(3)
    ] + [
        TrialResult(shape="shape1_fanout", mode="S-sequential", rep=i, wall_s=1.2,
                    waves_used=6, deferrals=0, corruption_files=0, corruption_incidents=0,
                    files_checked=6, starved=0, hangs=0, completed_nodes=6, total_nodes=6)
        for i in range(3)
    ]
    s = summarize_shape("shape1_fanout", rs)
    assert s["modes"]["G-dafg-graph"]["wall_s_mean"] == 0.4
    assert s["modes"]["G-dafg-graph"]["completion_rate"] == 1.0
    assert s["modes"]["G-dafg-graph"]["corruption_rate"] == 0.0
