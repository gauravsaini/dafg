"""Unified CLI for DAFG framework."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import List, Optional

from dafg.gates import ApprovalStore, GateEngine, GateLedger, GateLinter
from dafg.hook import CompletionGuard
from dafg.runtime import DAFG, Budget, TaskNode


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        parser = argparse.ArgumentParser(
            prog="dafg",
            description="Python-native agent coordination and completion-discipline framework",
        )
        parser.add_argument("command", choices=["gates", "stop-hook", "run", "eval", "audit", "init", "organism", "compare"], help="Sub-commands")
        parser.print_help()
        return 0

    cmd = argv[0]
    sub_args = argv[1:]

    if cmd == "gates":
        from dafg import gates
        return gates.main(sub_args)

    elif cmd == "stop-hook":
        from dafg import hook
        return hook.main(sub_args)

    elif cmd == "run":
        parser = argparse.ArgumentParser(prog="dafg run", description="Run DAFG workflow")
        parser.add_argument("--state", default="state.json", help="Path to state.json")
        parser.add_argument("--gates", default="GATES.md", help="Path to GATES.md")
        parser.add_argument("--approvals-file", default=".approved_gates.json", help="Path to approvals file")
        parser.add_argument("--auto-approve", action="store_true", help="Auto approve check commands")
        parser.add_argument("--enforce-safe-policy", action="store_true", help="Enforce SafeCommandPolicy sandbox on check commands")
        parser.add_argument("--no-analytics", action="store_true", help="Suppress analytics report")
        parser.add_argument("--json-analytics", action="store_true", help="Print analytics as JSON")
        parser.add_argument("--judge", action="store_true", help="Print standalone Run Quality Report from Analytics Judge")
        parser.add_argument(
            "--observe",
            action="append",
            default=[],
            help="Observability probes (e.g. 'jsonl:path', 'stdout', 'memory', 'all', 'none')",
        )
        args = parser.parse_args(sub_args)

        # Print trend briefing if available
        try:
            from dafg.trends import TrendStore, TrendAnalyzer
            store = TrendStore(filepath=Path("eval_results/trends.jsonl"))
            if store.filepath.exists():
                analyzer = TrendAnalyzer(store)
                briefing = analyzer.generate_briefing()
                if briefing and "No previous runs" not in briefing:
                    print(briefing)
                    print()  # blank line separator
        except Exception:
            pass  # Trend briefing is best-effort

        from dafg.observe import parse_observe_flag
        probes = parse_observe_flag(args.observe) if args.observe else None

        gates_fp = Path(args.gates)
        ledger = GateLedger.load(gates_fp) if gates_fp.exists() else None
        appr_store = ApprovalStore(filepath=args.approvals_file)
        enforce_safe = args.enforce_safe_policy
        engine = GateEngine(approval_store=appr_store, auto_approve=args.auto_approve, enforce_safe_policy=enforce_safe) if ledger else None
        state_fp = Path(args.state)
        if state_fp.exists():
            graph = DAFG.load_state(state_fp, ledger=ledger, engine=engine, probes=probes)
            print(f"Resumed DAFG from {state_fp} with {len(graph.nodes)} nodes.")
            if ledger:
                created = graph.init_from_ledger()
                if created:
                    print(f"Synchronized {len(created)} new tasks from {gates_fp}.")
        else:
            graph = DAFG(ledger=ledger, engine=engine, state_path=state_fp, probes=probes)
            if ledger and not graph.nodes:
                created = graph.init_from_ledger()
                print(f"Initialized new DAFG with {len(created)} tasks from {gates_fp}.")
            else:
                print(f"Initialized new DAFG with state file {state_fp}.")
        result = graph.run()
        print(f"DAFG run status: {result}")
        if args.judge:
            from dafg.judge import RunJudge
            report = RunJudge.evaluate(graph)
            print()
            print(report.format_report())
        elif not args.no_analytics:
            if args.json_analytics:
                import json
                print(json.dumps(graph.get_run_analytics(), indent=2))
            else:
                print()
                print(graph.format_analytics_report())
        return 0 if result == "COMPLETED" else 1

    elif cmd == "eval":
        parser = argparse.ArgumentParser(prog="dafg eval", description="Run DAFG Benchmark Evaluation Suite")
        parser.add_argument("--suite", choices=["v02-regression", "v03"], default="v03", help="Benchmark suite")
        parser.add_argument("--tier", choices=["dev", "calibration", "held_out"], default=None, help="Benchmark tier for v03")
        parser.add_argument("--adapter", choices=["cli", "dispatch", "react", "all"], default="cli", help="Execution adapter (or 'all' for full matrix)")
        parser.add_argument("--all-adapters", action="store_true", help="Evaluate across all three adapters and generate full matrix")
        parser.add_argument("--out", default=None, help="Output JSON file path")
        parser.add_argument("--json", action="store_true", help="Output summary JSON")
        args = parser.parse_args(sub_args)

        import json
        from dafg.eval import EvaluationHarness
        from dafg.adapters import IterativeCLIAdapter, ToolDispatchAdapter, ReActStateAdapter

        eval_dir = Path("eval_results")
        eval_dir.mkdir(parents=True, exist_ok=True)

        adapters_to_run = ["cli", "dispatch", "react"] if (args.all_adapters or args.adapter == "all") else [args.adapter]
        tier_suffix = f"_{args.tier}" if args.tier else ""
        matrix_file = eval_dir / f"benchmark_matrix_{args.suite}{tier_suffix}.json"

        last_metrics = None
        for ad_name in adapters_to_run:
            if ad_name == "cli":
                adapter = IterativeCLIAdapter()
            elif ad_name == "dispatch":
                adapter = ToolDispatchAdapter()
            else:
                adapter = ReActStateAdapter()

            harness = EvaluationHarness()
            tasks = harness.load_builtin_tasks(suite=args.suite, tier=args.tier)
            if not args.json:
                print(f"Running benchmark '{args.suite}' (tier: {args.tier or 'all'}) with adapter '{adapter.name}' across {len(tasks)} tasks...")

            for task in tasks:
                harness.run_trial(task, adapter=adapter, condition_name=ad_name)

            metrics = harness.compute_metrics(condition=ad_name)
            last_metrics = metrics

            out_file = Path(args.out) if (args.out and len(adapters_to_run) == 1) else eval_dir / f"benchmark_{args.suite}{tier_suffix}_{ad_name}.json"
            harness.save_results(out_file, suite=args.suite, adapter_name=ad_name, tier=args.tier)
            EvaluationHarness.update_benchmark_matrix(
                matrix_file, suite=args.suite, adapter_name=ad_name, metrics=metrics, trials=harness.trials, tier=args.tier
            )
            if not args.json:
                print(f"[{ad_name.upper()}] Persisted trial telemetry to {out_file}")
                print("=" * 60)
                print(f"BENCHMARK EVALUATION RESULTS ({args.suite.upper()} - {adapter.name})")
                print("=" * 60)
                print(f"Total Trials:                {metrics.total_trials}")
                print(f"Correct-Outcome Rate:        {metrics.correct_outcome_rate * 100:.1f}% ({metrics.correct_outcomes}/{metrics.total_trials})")
                print(f"Delivery Success (Feasible): {metrics.delivery_success_rate * 100:.1f}% ({metrics.verified_success_count}/{metrics.feasible_trials})")
                print(f"Correct Blocking (Imposs.):  {metrics.correct_block_rate * 100:.1f}% ({metrics.correct_block_count}/{metrics.impossible_trials})")
                print(f"Tokens / Correct Outcome:    {metrics.tokens_per_correct_outcome:.0f}")
                print("=" * 60)

        if not args.json:
            print(f"Updated benchmark matrix at {matrix_file}")
        else:
            if len(adapters_to_run) > 1:
                with open(matrix_file, "r") as f:
                    matrix_data = json.load(f)
                print(json.dumps(matrix_data, indent=2))
            elif last_metrics:
                print(json.dumps(last_metrics.to_dict(), indent=2))
        return 0

    elif cmd == "audit":
        parser = argparse.ArgumentParser(prog="dafg audit", description="Run DAFG Protocol Formal Conformance Audit")
        parser.add_argument("--protocol", action="store_true", default=True, help="Run formal protocol state machine audit")
        parser.add_argument("--trace", default=None, help="Path to domain events JSON trace to audit")
        parser.add_argument("--state", default=None, help="Path to state.json to audit")
        parser.add_argument("--gates", default="GATES.md", help="Path to GATES.md for evidence audit")
        parser.add_argument("--out", default=None, help="Output audit report path")
        parser.add_argument("--json", action="store_true", help="Output audit report as JSON")
        args = parser.parse_args(sub_args)

        import json
        from dafg.eval import ProtocolAuditRunner

        runner = ProtocolAuditRunner()
        if args.trace:
            trace_p = Path(args.trace)
            if not trace_p.exists():
                report = {
                    "passed": False,
                    "events_analyzed": 0,
                    "violations": [f"Trace file '{args.trace}' does not exist (TRACE_FILE_NOT_FOUND)"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            else:
                with open(trace_p, "r", encoding="utf-8") as f:
                    trace_data = json.load(f)
                report = runner.audit_event_trace(trace_data)
        elif args.state:
            gates_fp = Path(args.gates)
            ledger = GateLedger.load(gates_fp) if gates_fp.exists() else None
            report = runner.audit_state(args.state, ledger=ledger)
        else:
            report = runner.run_all()

        eval_dir = Path("eval_results")
        eval_dir.mkdir(parents=True, exist_ok=True)
        audit_file = Path(args.out) if args.out else eval_dir / "audit_report.json"
        with open(audit_file, "w") as f:
            json.dump(report, f, indent=2)

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("=" * 60)
            print("DAFG FORMAL PROTOCOL CONFORMANCE AUDIT")
            print("=" * 60)
            if "checks" in report:
                for check_name, passed in report["checks"].items():
                    mark = "[PASS]" if passed else "[FAIL]"
                    print(f"{mark} {check_name}")
                print("=" * 60)
                status_str = "PASSED" if report["passed"] else "FAILED"
                print(f"Overall Result: {status_str} ({report['passed_checks']}/{report['total_checks']} checks)")
            else:
                status_str = "PASSED" if report["passed"] else "FAILED"
                print(f"Overall Result: {status_str}")
                if report.get("violations"):
                    print(f"Violations detected ({len(report['violations'])}):")
                    for v in report["violations"]:
                        print(f"  - {v}")
                else:
                    print("0 violations found.")
            print(f"Persisted audit report to {audit_file}")
            print("=" * 60)
        return 0 if report["passed"] else 1

    elif cmd == "init":
        parser = argparse.ArgumentParser(prog="dafg init", description="Initialize DAFG acceptance gates and AI agent stop-hooks")
        parser.add_argument("--agents", default="all", help="Target agent platforms comma-separated: claude,codex,antigravity,cursor,copilot or 'all' (default: all)")
        parser.add_argument("--force", action="store_true", help="Overwrite existing configuration files")
        args = parser.parse_args(sub_args)
        from dafg.init import scaffold_project
        return scaffold_project(agents=args.agents, force=args.force)

    elif cmd == "organism":
        parser = argparse.ArgumentParser(
            prog="dafg organism",
            description="Autonomous Reactive & Self-Improving Execution Organism",
        )
        parser.add_argument("--goal", required=True, help="High-level goal string (e.g. 'Clone Redis key-value store')")
        parser.add_argument("--generations", type=int, default=4, help="Maximum evolutionary generations (default: 4)")
        parser.add_argument("--target-score", type=float, default=85.0, help="Target quality score for convergence (default: 85.0, aligned with PERFECT threshold)")
        parser.add_argument("--workdir", default=None, help="Directory to scaffold and evolve organism")
        parser.add_argument("--auto-approve", action="store_true", default=False, help="Explicitly authorize auto-approval of sandboxed synthesized checks")
        parser.add_argument("--json", action="store_true", help="Output lineage summary as JSON")
        args = parser.parse_args(sub_args)

        from dafg.organism import AutonomousOrganism
        import json

        organism = AutonomousOrganism(
            goal=args.goal,
            workdir=args.workdir,
            max_generations=args.generations,
            target_score=args.target_score,
            auto_approve=args.auto_approve,
        )

        def print_gen_update(record):
            if not args.json:
                print(f"  → Generation {record.generation} completed: Score {record.score:.1f}/100 ({record.verdict}), Gates {record.gates_met}/{record.gates_total} MET, FSI {record.friction_severity_index:.2f}")

        if not args.json:
            print("=" * 72)
            print("         DAFG AUTONOMOUS REACTIVE EXECUTION ORGANISM")
            print("=" * 72)
            print(f"Goal: {args.goal}")
            print(f"Target Quality Score: {args.target_score} | Max Generations: {args.generations}")
            if args.auto_approve:
                print("🔒 Security: --auto-approve enabled under SafeCommandPolicy sandbox.")
            else:
                print("🔒 Security Notice: Auto-approval disabled. Synthesized checks require explicit approval.")
            print("Initializing Autonomous Genesis...")

        lineage = organism.evolve_to_completion(generation_callback=print_gen_update)

        if args.json:
            print(json.dumps(lineage.to_dict(), indent=2))
        else:
            print()
            print(organism.format_lineage_dashboard())
        return 0 if lineage.converged else 1

    elif cmd == "compare":
        parser = argparse.ArgumentParser(prog="dafg compare", description="Compare experiment runs programmatically")
        parser.add_argument("experiments", nargs="+", help="Paths to experiment directories")
        parser.add_argument("--json", action="store_true", help="Output comparison matrix as JSON")
        parser.add_argument("--fresh", action="store_true", help="Execute a fresh, unified run across all experiment directories")
        parser.add_argument("--generations", action="store_true", help="Expand generation subdirectories")
        args = parser.parse_args(sub_args)

        from dafg.compare import ExperimentComparator
        dirs: List[Path] = []
        for p in args.experiments:
            exp_p = Path(p)
            gen_dir = exp_p / "generations"
            if args.generations and gen_dir.is_dir():
                sub_dirs = sorted([d for d in gen_dir.iterdir() if d.is_dir()])
                if sub_dirs:
                    dirs.extend(sub_dirs)
                    continue
            dirs.append(exp_p)

        records = [ExperimentComparator.analyze_dir(d, fresh=args.fresh) for d in dirs]
        if args.json:
            import json
            print(json.dumps([r.to_dict() for r in records], indent=2))
        else:
            md = ExperimentComparator.generate_markdown_table(records)
            print(md)
        return 0

    elif cmd in ("-h", "--help"):
        parser = argparse.ArgumentParser(
            prog="dafg",
            description="Python-native agent coordination and completion-discipline framework",
        )
        parser.add_argument("command", choices=["gates", "stop-hook", "run", "eval", "audit", "init", "organism", "compare"], help="Sub-commands")
        parser.print_help()
        return 0

    else:
        print(f"Error: Unknown command '{cmd}'. Choose from 'gates', 'stop-hook', 'run', 'eval', 'audit', 'init', 'organism', 'compare'.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
