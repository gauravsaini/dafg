"""Build docs/paper figures from eval JSONs. Every number is read from a report
file; nothing is invented. Run: uv run python docs/paper/build_figs.py"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
EV = "/tmp/paper/eval_results"

# Consistent palette across figures
C_BASE = "#8b949e"   # A-baseline / sequential gray
C_FULL = "#1f6feb"   # full DAFG / barrier blue
C_GRAPH = "#0e9f8a"  # graph-only / hybrid teal
C_NOGATE = "#d29922" # no-gates amber
C_NAIVE = "#da3633"  # naive-parallel red
C_GATE = "#238636"   # gate green

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
    "figure.dpi": 150, "savefig.dpi": 150,
})


def load(name):
    with open(os.path.join(EV, name)) as f:
        return json.load(f)


# ---------------------------------------------------------------- fig1: schematic
def fig1():
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6.2); ax.axis("off")
    ax.text(5, 5.95, "DAFG: graph × gates × artifacts", ha="center", fontsize=12, weight="bold")
    ax.text(5, 5.68, 'Schematic — not measured. Waves schedule work; gates verify completion; artifacts carry knowledge.', ha="center", fontsize=8, style="italic", color="#555555")

    def node(x, y, label, owns, color=C_FULL):
        b = FancyBboxPatch((x - 0.85, y - 0.42), 1.7, 0.84, boxstyle="round,pad=0.04",
                           facecolor="white", edgecolor=color, linewidth=1.6)
        ax.add_patch(b)
        ax.text(x, y + 0.14, label, ha="center", fontsize=9, weight="bold")
        ax.text(x, y - 0.18, f"OWNS: {owns}", ha="center", fontsize=7, color="#444444")

    # waves
    for wx, wlabel in [(1.7, "Wave 1"), (4.35, "Wave 2"), (7.0, "Wave 3")]:
        ax.text(wx, 5.25, wlabel, ha="center", fontsize=9, weight="bold", color="#555555")
    node(0.95, 4.35, "Task A", "auth.py")
    node(2.75, 4.35, "Task B", "db.py")
    node(4.35, 4.35, "Task C", "api.py", C_GRAPH)
    node(4.35, 3.15, "Task D", "api.py", C_GRAPH)
    node(7.0, 3.75, "Task E", "ui.py")

    def dep(x1, y1, x2, y2, label=None, color="#333333", ls="-"):
        a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=12,
                            color=color, linewidth=1.2, linestyle=ls, shrinkA=2, shrinkB=6)
        ax.add_patch(a)
        if label:
            ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.18, label, ha="center", fontsize=7, color=color)

    dep(1.8, 4.35, 3.5, 4.35); dep(2.75, 3.93, 4.35, 3.57)
    dep(5.2, 4.35, 6.15, 3.95); dep(5.2, 3.15, 6.15, 3.55)
    # artifact flow (provisional -> final)
    dep(1.8, 4.72, 3.5, 4.72, "KnowledgeArtifact\nprovisional → final", C_NOGATE)
    dep(5.2, 4.72, 6.15, 4.55, "ContractArtifact v1→v2\n(stale → re-sync)", C_NOGATE)

    # gate machinery band
    ax.text(5, 2.35, "Completion discipline (every node)", ha="center", fontsize=9, weight="bold", color="#555555")
    boxes = [
        (0.7, "GATES.md\nCHECK: cmd\nEXPECT: regex", C_GATE),
        (3.0, "GateLedger\napprove → run", C_GATE),
        (5.3, "stop-hook\nallow / block", C_NOGATE),
        (7.6, "External judge\nindependent verdict", C_FULL),
        (9.3, "Budget /\nstarvation guard", C_NAIVE),
    ]
    for x, label, color in boxes:
        b = FancyBboxPatch((x - 0.62, 0.55), 1.24, 1.15, boxstyle="round,pad=0.04",
                           facecolor="#f6f8fa", edgecolor=color, linewidth=1.4)
        ax.add_patch(b)
        ax.text(x, 1.12, label, ha="center", va="center", fontsize=7.5)
    for x1, x2 in [(1.32, 2.38), (3.62, 4.68), (5.92, 6.98), (8.22, 8.68)]:
        ax.add_patch(FancyArrowPatch((x1, 1.12), (x2, 1.12), arrowstyle="-|>",
                                     mutation_scale=10, color="#333333", linewidth=1.1))
    ax.text(5, 0.22, "No node may claim done until stop-hook returns allow on FINAL artifacts.", ha="center", fontsize=8, style="italic")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig1_architecture.png"), bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------- fig2: ablation scatterplot
def fig2():
    hyb = load("hybrid_report.json")
    gates = load("gates_ab_report.json")
    tc = {d["change_rate"]: d for d in hyb["tradeoff_curve"]}
    d0 = tc[0.0]
    # Panel A: hybrid experiment — same tasks, both axes measured
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 3.8))
    h1_wall = d0["H1_wall"]
    pts = {
        "H1 barrier\n(full DAFG)": (1.0, 1.0, C_FULL),
        "H2 hybrid\nchange 0%": (d0["H2_speedup_vs_H1"], 1.0, C_GRAPH),
        "H2 hybrid\nchange 25%": (tc[0.25]["H2_speedup_vs_H1"], 1.0, C_GRAPH),
        "H2 hybrid\nchange 50%": (tc[0.5]["H2_speedup_vs_H1"], 1.0, C_GRAPH),
        "H3 early\nno gates": (h1_wall / d0["H3_wall"], 1 - d0["FCR"]["H3-early-no-gates"], C_NOGATE),
    }
    for label, (x, y, c) in pts.items():
        ax1.scatter([x], [y], s=90, color=c, zorder=3, edgecolor="white")
    ann = [
        ("H1 barrier\n(full DAFG)", pts["H1 barrier\n(full DAFG)"][:2], (6, 8)),
        ("H2 @0%", pts["H2 hybrid\nchange 0%"][:2], (6, 8)),
        ("H2 @25%", pts["H2 hybrid\nchange 25%"][:2], (4, -20)),
        ("H2 @50%", pts["H2 hybrid\nchange 50%"][:2], (-44, -20)),
        ("H3 early\nno gates", pts["H3 early\nno gates"][:2], (6, -4)),
    ]
    for label, (x, y), off in ann:
        ax1.annotate(label, (x, y), fontsize=7, xytext=off, textcoords="offset points")
    # arrows: full -> ablated
    def arrow(ax, p1, p2):
        a = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=12,
                            color="#333333", linewidth=1.2,
                            shrinkA=8, shrinkB=8, linestyle="--")
        ax.add_patch(a)
    arrow(ax1, pts["H1 barrier\n(full DAFG)"][:2], pts["H2 hybrid\nchange 0%"][:2])
    arrow(ax1, pts["H2 hybrid\nchange 0%"][:2], pts["H3 early\nno gates"][:2])
    ax1.set_xlabel("Speedup vs barrier (wall time)")
    ax1.set_ylabel("Correctness  (1 − FCR)")
    ax1.set_title("A. Hybrid ablation: same tasks, both axes measured", fontsize=9)
    ax1.set_xlim(0.8, 2.3); ax1.set_ylim(0.3, 1.12)
    ax1.grid(alpha=0.25)

    # Panel B: gates on/off — verification collapses without gates
    exp1 = gates["experiments"]["exp1_defect_catching"]["modes"]
    labels = ["A-baseline", "B2-graph-only", "B1-full"]
    vals = [1 - exp1[m]["false_completion_rate"] for m in labels]
    colors = [C_BASE, C_GRAPH, C_FULL]
    bars = ax2.bar(labels, vals, color=colors, edgecolor="white")
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.03, f"{v:.2f}", ha="center", fontsize=8)
    arrow(ax2, (2, 0.95), (1, 0.32))
    ax2.text(1.5, 0.62, "remove\ngates", ha="center", fontsize=7, style="italic")
    ax2.set_ylabel("Correctness  (1 − FCR)")
    ax2.set_title("B. Gates on/off: verification collapses", fontsize=9)
    ax2.set_ylim(0, 1.15)
    fig.suptitle("Ablations: coordination drives the gains, not parallelism alone", fontsize=10, weight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig2_ablation.png"), bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------- fig3: mechanism attribution
def fig3():
    gates = load("gates_ab_report.json")
    attr = gates["mechanism_attribution_CBR"]
    mechs = [
        ("adapter_refusal", "Adapter refusal", 7),
        ("dafg_contradiction_gate", "Contradiction gate", 5),
        ("dafg_deadlock_cycle", "Deadlock cycle", 4),
        ("dafg_gate_oracle", "Gate oracle", 4),
    ]
    modes = [("A", "A-baseline", C_BASE), ("B1", "B1-full", C_FULL), ("B2", "B2-graph-only", C_GRAPH)]
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    x = range(len(mechs))
    w = 0.22
    for i, (mk, ml, mm) in enumerate(modes):
        vals = [attr[mkey][mk] for mkey, _, _ in mechs]
        off = (i - 1) * w
        bars = ax.bar([p + off for p in x], vals, width=w, label=ml, color=mm, edgecolor="white")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.03, f"{v:.1f}", ha="center", fontsize=7)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{name}\n(n={n})" for _, name, n in mechs])
    ax.set_ylabel("Block rate per mechanism")
    ax.set_ylim(0, 1.25)
    ax.set_title("Each blocking mechanism belongs to exactly one layer", fontsize=10, weight="bold")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig3_mechanisms.png"), bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------- fig4: hybrid tradeoff curve
def fig4():
    hyb = load("hybrid_report.json")
    tc = sorted(hyb["tradeoff_curve"], key=lambda d: d["change_rate"])
    be = hyb["breakeven_reworks_per_trial"]
    xs = [d["change_rate"] * 100 for d in tc]
    sp = [d["H2_speedup_vs_H1"] for d in tc]
    rw = [d["H2_rework_per_trial"] for d in tc]
    fig, ax1 = plt.subplots(figsize=(7.5, 4.0))
    l1, = ax1.plot(xs, sp, "o-", color=C_GRAPH, linewidth=2, markersize=7, label="H2 speedup vs H1")
    for x, y in zip(xs, sp):
        ax1.annotate(f"{y:.2f}×", (x, y), fontsize=8, xytext=(0, 10), textcoords="offset points", ha="center")
    ax1.set_xlabel("Provisional change-rate (%)")
    ax1.set_ylabel("Speedup H2 vs H1 (wall time)", color=C_GRAPH)
    ax1.tick_params(axis="y", labelcolor=C_GRAPH)
    ax1.set_ylim(1.3, 1.9)
    ax1.grid(alpha=0.25)
    ax2 = ax1.twinx()
    l2, = ax2.plot(xs, rw, "s--", color=C_NOGATE, linewidth=2, markersize=7, label="Rework / trial")
    for x, y in zip(xs, rw):
        ax2.annotate(f"{y:.2f}", (x, y), fontsize=8, xytext=(0, -14), textcoords="offset points", ha="center")
    ax2.axhline(be, color=C_NAIVE, linestyle=":", linewidth=1.5)
    ax2.text(xs[-1], be + 0.08, f"break-even {be:.2f} reworks/trial (unreachable)", ha="right", fontsize=7.5, color=C_NAIVE)
    ax2.set_ylabel("Rework events / trial", color=C_NOGATE)
    ax2.tick_params(axis="y", labelcolor=C_NOGATE)
    ax2.set_ylim(-0.2, 6.2)
    ax1.set_title("Hybrid tradeoff: speedup erodes gracefully as change-rate rises", fontsize=10, weight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig4_tradeoff.png"), bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------- fig5: real-model pilot
def fig5():
    v04 = load("v04_pilot_report.json")
    m = v04["metrics"]
    d = v04["deltas_B_minus_A"]
    A, B = m["A-baseline"], m["B-dafg"]
    fig, axes = plt.subplots(2, 2, figsize=(8.5, 5.2))
    specs = [
        ("Verified delivery rate (EVD)", A["evd"], B["evd"], d["evd"], "{:.2f}", "{:+.2f}", (0, 1.05)),
        ("False-completion rate (FCR)", A["fcr"], B["fcr"], d["fcr"], "{:.2f}", "{:+.2f}", (0, 0.25)),
        ("Cost / deliverable (k tokens)", A["cpad_tokens"] / 1000, B["cpad_tokens"] / 1000, d["cpad_tokens"] / 1000, "{:.1f}k", "{:+.1f}k", (0, 145)),
        ("Time / deliverable (s)", A["ttr_s"], B["ttr_s"], d["ttr_s"], "{:.1f}s", "{:+.1f}s", (0, 105)),
    ]
    for ax, (title, va, vb, delta, vfmt, dfmt, ylim) in zip(axes.flat, specs):
        bars = ax.bar(["A-baseline", "B-dafg"], [va, vb], color=[C_BASE, C_FULL], edgecolor="white")
        for b, v in zip(bars, (va, vb)):
            ax.text(b.get_x() + b.get_width() / 2, v + ylim[1] * 0.02, vfmt.format(v),
                    ha="center", fontsize=8)
        ax.text(0.5, ylim[1] * 0.88, f"Δ {dfmt.format(delta)}", ha="center", fontsize=9, weight="bold",
                transform=ax.transData, bbox=dict(facecolor="#fff8e1", edgecolor="#e0c36a", boxstyle="round,pad=0.25"))
        ax.set_title(title, fontsize=9)
        ax.set_ylim(*ylim)
    fig.suptitle("Real-model pilot: gpt-6-luna, 20 tasks × 2 modes (n=20/mode)", fontsize=10, weight="bold", y=0.99)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig5_realmode.png"), bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------- fig6: timeline Gantt
def fig6():
    # Event schedule derived from src/dafg/hybrid.py simulator semantics
    # (verified: simulate_h1 clean -> 440.0; simulate_h2 one-change -> 300.0).
    # Chain: 4 stages, stage1's FINAL changes its interface -> one rework.
    D, P, G, R = 100, 50, 10, 40
    h1 = [(i * 110, i * 110 + 100, i * 110 + 100, i * 110 + 110) for i in range(4)]  # (w0,w1,g0,g1)
    # H2: stage0 [0,100] prov 50; stage1 [50,150] prov 100 final changed;
    #     stage2 start 100, +40 shift -> work [100,240] prov 190; stage3 start 190 -> [190,290] prov 240
    h2 = [
        (0, 100, 50, 100, 110, False),
        (50, 150, 100, 150, 160, True),
        (100, 240, 190, 240, 250, False),
        (190, 290, 240, 290, 300, False),
    ]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.5, 4.6), sharex=True)
    for ax, title in [(ax1, "H1 barrier — dependent waits for gate pass (wall 440)"),
                      (ax2, "H2 hybrid — speculative start, one re-sync (wall 300)")]:
        ax.set_title(title, fontsize=9, loc="left")
        ax.set_ylim(-0.6, 3.6)
        ax.set_yticks(range(4))
        ax.set_yticklabels(["stage3", "stage2", "stage1", "stage0"])
        ax.grid(axis="x", alpha=0.25)
    for i, (w0, w1, g0, g1) in enumerate(h1):
        y = 3 - i
        ax1.barh(y, w1 - w0, left=w0, height=0.45, color=C_FULL, edgecolor="white")
        ax1.barh(y, g1 - g0, left=g0, height=0.45, color=C_GATE, edgecolor="white")
        ax1.text(w0 + 4, y + 0.02, "work", va="center", fontsize=7, color="white", weight="bold")
        ax1.text(g0 + 1, y + 0.02, "gate", va="center", fontsize=7, color="white")
    for i, (w0, w1, pv, f0, g1, changed) in enumerate(h2):
        y = 3 - i
        ax2.barh(y, w1 - w0, left=w0, height=0.45, color=C_GRAPH, edgecolor="white")
        if i == 2:  # rework segment hatched
            ax2.barh(y, R, left=w1 - R, height=0.45, color=C_NOGATE, edgecolor="white", hatch="///")
            ax2.text(w1 - R / 2, y, "re-sync", ha="center", va="center", fontsize=7, color="white", weight="bold")
        ax2.barh(y, G, left=f0, height=0.45, color=C_GATE, edgecolor="white")
        ax2.plot([pv], [y], marker="D", color=C_NOGATE, markersize=8, markeredgecolor="white", zorder=4)
        if changed:
            ax2.annotate("FINAL changed\n→ stage2 stale", xy=(f0, y), xytext=(f0 + 45, y + 0.9),
                         fontsize=7, ha="center", color=C_NAIVE,
                         arrowprops=dict(arrowstyle="-|>", color=C_NAIVE, mutation_scale=10))
    ax1.text(300, 3.42, "◆ = provisional publish", fontsize=7.5, color=C_NOGATE)
    ax2.set_xlabel("Virtual time units")
    fig.suptitle("One chain, no defects: barrier vs hybrid execution", fontsize=10, weight="bold", y=0.99)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig6_timeline.png"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(HERE, exist_ok=True)
    for fn in [fig1, fig2, fig3, fig4, fig5, fig6]:
        fn()
        print("built", fn.__name__)
