"""Unified CLI for DAFG framework."""

from __future__ import annotations

import argparse
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
        parser.add_argument("command", choices=["gates", "stop-hook", "run", "eval", "audit"], help="Sub-commands")
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
        args = parser.parse_args(sub_args)

        gates_fp = Path(args.gates)
        ledger = GateLedger.load(gates_fp) if gates_fp.exists() else None
        appr_store = ApprovalStore(filepath=args.approvals_file)
        engine = GateEngine(approval_store=appr_store, auto_approve=args.auto_approve) if ledger else None
        state_fp = Path(args.state)
        if state_fp.exists():
            graph = DAFG.load_state(state_fp, ledger=ledger, engine=engine)
            print(f"Resumed DAFG from {state_fp} with {len(graph.nodes)} nodes.")
            if ledger and not graph.nodes:
                created = graph.init_from_ledger()
                print(f"Initialized DAFG with {len(created)} tasks from {gates_fp}.")
        else:
            graph = DAFG(ledger=ledger, engine=engine, state_path=state_fp)
            if ledger and not graph.nodes:
                created = graph.init_from_ledger()
                print(f"Initialized new DAFG with {len(created)} tasks from {gates_fp}.")
            else:
                print(f"Initialized new DAFG with state file {state_fp}.")
        result = graph.run()
        print(f"DAFG run status: {result}")
        return 0 if result == "COMPLETED" else 1

    elif cmd == "eval":
        parser = argparse.ArgumentParser(prog="dafg eval", description="Run DAFG Benchmark Evaluation Suite")
        parser.add_argument("--suite", choices=["v02-regression", "v03"], default="v03", help="Benchmark suite")
        parser.add_argument("--tier", choices=["dev", "calibration", "held_out"], default=None, help="Benchmark tier for v03")
        parser.add_argument("--adapter", choices=["cli", "dispatch", "react"], default="cli", help="Execution adapter")
        parser.add_argument("--json", action="store_true", help="Output summary JSON")
        args = parser.parse_args(sub_args)

        import json
        from dafg.eval import EvaluationHarness
        from dafg.adapters import IterativeCLIAdapter, ToolDispatchAdapter, ReActStateAdapter

        if args.adapter == "cli":
            adapter = IterativeCLIAdapter()
        elif args.adapter == "dispatch":
            adapter = ToolDispatchAdapter()
        else:
            adapter = ReActStateAdapter()

        harness = EvaluationHarness()
        tasks = harness.load_builtin_tasks(suite=args.suite, tier=args.tier)
        print(f"Running benchmark '{args.suite}' (tier: {args.tier or 'all'}) with adapter '{adapter.name}' across {len(tasks)} tasks...")

        for task in tasks:
            harness.run_trial(task, adapter=adapter, condition_name=args.adapter)

        metrics = harness.compute_metrics()
        if args.json:
            print(json.dumps(metrics.to_dict(), indent=2))
        else:
            print("=" * 60)
            print(f"BENCHMARK EVALUATION RESULTS ({args.suite.upper()})")
            print("=" * 60)
            print(f"Total Trials:                {metrics.total_trials}")
            print(f"Correct-Outcome Rate:        {metrics.correct_outcome_rate * 100:.1f}% ({metrics.correct_outcomes}/{metrics.total_trials})")
            print(f"Delivery Success (Feasible): {metrics.delivery_success_rate * 100:.1f}% ({metrics.verified_success_count}/{metrics.feasible_trials})")
            print(f"Correct Blocking (Imposs.):  {metrics.correct_block_rate * 100:.1f}% ({metrics.correct_block_count}/{metrics.impossible_trials})")
            print(f"Tokens / Correct Outcome:    {metrics.tokens_per_correct_outcome:.0f}")
            print("=" * 60)
        return 0

    elif cmd == "audit":
        parser = argparse.ArgumentParser(prog="dafg audit", description="Run DAFG Protocol Formal Conformance Audit")
        parser.add_argument("--protocol", action="store_true", default=True, help="Run formal protocol state machine audit")
        parser.add_argument("--json", action="store_true", help="Output audit report as JSON")
        args = parser.parse_args(sub_args)

        import json
        from dafg.eval import ProtocolAuditRunner

        runner = ProtocolAuditRunner()
        report = runner.run_all()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("=" * 60)
            print("DAFG FORMAL PROTOCOL CONFORMANCE AUDIT")
            print("=" * 60)
            for check_name, passed in report["checks"].items():
                mark = "[PASS]" if passed else "[FAIL]"
                print(f"{mark} {check_name}")
            print("=" * 60)
            status_str = "PASSED" if report["passed"] else "FAILED"
            print(f"Overall Result: {status_str} ({report['passed_checks']}/{report['total_checks']} checks)")
            print("=" * 60)
        return 0 if report["passed"] else 1

    elif cmd in ("-h", "--help"):
        parser = argparse.ArgumentParser(
            prog="dafg",
            description="Python-native agent coordination and completion-discipline framework",
        )
        parser.add_argument("command", choices=["gates", "stop-hook", "run", "eval", "audit"], help="Sub-commands")
        parser.print_help()
        return 0

    else:
        print(f"Error: Unknown command '{cmd}'. Choose from 'gates', 'stop-hook', 'run', 'eval', 'audit'.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
