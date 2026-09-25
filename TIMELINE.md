## UPDATED ON : 2026-09-24

### feat (2026-09-24) — Verification-first control plane & completion integrity

1. **Thesis Lock**: Locked primary product thesis to completion-integrity control plane; deferred streaming mechanisms to optional performance experiments.
2. **Eval Manifest**: Added `EvaluationManifest` for reproducible benchmark provenance tracking run IDs, commit hashes, and environment digests.
3. **Evidence Status**: Updated `ExperimentComparator` with strict `evidence_status` validation, rejecting missing run IDs, hash mismatches, and malformed ground truth.
4. **Acceptance Gates**: Added G14 (canonical product direction), G15 (eval provenance), and G16 (comparison evidence verification).
5. **Tests** (before → after): 747 passed → full suite 757 passed, 0 failed via uv run pytest -q.
6. **Files changed**: `GOAL.md`, `README.md`, `plan.md`, `GATES.md`, `src/dafg/cli.py`, `src/dafg/compare.py`, `src/dafg/eval.py`, `tests/test_boeing747.py`, `tests/test_compare.py`, `tests/test_eval_provenance.py`

## UPDATED ON : 2026-09-24

### feat (2026-09-24) — Verified fault injection & baseline comparison slice

1. **Fault Operators**: Implemented six deterministic fault operators (`syntax_break`, `logic_flip`, `concurrency_race`, `facade_stub`, `scope_violation`, `unsatisfiable_constraint`) with AST-safe `logic_flip` for mutation testing and failure calibration.
2. **Baseline Comparison**: Added baseline-vs-verified comparison module (`phase1_compare.py`) exposing false completion claims vs externally verified ground-truth outcomes.
3. **Acceptance Gates**: Recorded G22 (detectable fault injection) and G23 (false completion exposure) evidence, reaching full gate count 23/23 MET.
4. **Tests** (before → after): 771 passed → 784 passed.
5. **Files changed**: `src/dafg/faults.py`, `src/dafg/phase1_compare.py`, `src/dafg/__init__.py`, `GATES.md`, `tests/test_fault_injection.py`, `tests/test_phase1_comparison.py`

## UPDATED ON : 2026-09-26

### feat (2026-09-26) — Calibrated fault matrix & defect-sensitivity evaluation

1. **Calibrated Fault Matrix**: Executed calibrated fault run over 130 rows (55 original, 55 mutated, 20 impossible); detected 37 defects, exposing a 28.46% false-completion rate.
2. **Class Detection Breakdown**: Measured class detection: syntax 10/10, logic 9/9, concurrency 0/9, facade 0/9, security 9/9, unsatisfiable 9/9.
3. **Ledger & Exports**: Added pending G24 to `GATES.md`; exported `run_calibrated_fault_matrix`, `FaultMatrixResult`, and `FaultMatrixRow` from `dafg`.
4. **Files changed**: `GATES.md`, `src/dafg/__init__.py`, `TIMELINE.md`
