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
        parser.add_argument("command", choices=["gates", "stop-hook", "run"], help="Sub-commands")
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

    elif cmd in ("-h", "--help"):
        parser = argparse.ArgumentParser(
            prog="dafg",
            description="Python-native agent coordination and completion-discipline framework",
        )
        parser.add_argument("command", choices=["gates", "stop-hook", "run"], help="Sub-commands")
        parser.print_help()
        return 0

    else:
        print(f"Error: Unknown command '{cmd}'. Choose from 'gates', 'stop-hook', 'run'.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
