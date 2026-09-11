"""Stage profiler and diagnostic metric computer for DAFG."""

from collections import defaultdict
from typing import Dict, List
from dafg_eval.telemetry.spans import TraceSpan, DAFGStage, ReasonCode

class StageProfiler:
    def __init__(self, spans: List[TraceSpan]):
        self.spans = spans

    def profile_all_stages(self) -> Dict[str, Dict]:
        stage_data = defaultdict(lambda: {
            'count': 0,
            'total_duration_sec': 0.0,
            'critical_path_duration_sec': 0.0,
            'total_tokens': 0,
            'cost_usd': 0.0,
            'defects_introduced': 0,
            'defects_detected': 0,
            'defects_repaired': 0,
            'revisions_triggered': 0,
            'reasons': defaultdict(int)
        })

        total_tokens_all = sum(s.input_tokens + s.output_tokens for s in self.spans) or 1
        total_dur_all = sum(s.duration_sec for s in self.spans) or 1.0

        for s in self.spans:
            st = stage_data[s.stage]
            st['count'] += 1
            dur = s.duration_sec
            tokens = s.input_tokens + s.output_tokens
            st['total_duration_sec'] += dur
            if s.is_critical_path:
                st['critical_path_duration_sec'] += dur
            st['total_tokens'] += tokens
            st['cost_usd'] += s.cost_usd
            if s.defect_introduced:
                st['defects_introduced'] += 1
            if s.defect_detected:
                st['defects_detected'] += 1
            if s.defect_repaired:
                st['defects_repaired'] += 1
            if s.decision in ['REVISE', 'INVALIDATE']:
                st['revisions_triggered'] += 1
            if s.reason_code != ReasonCode.NONE:
                st['reasons'][s.reason_code] += 1

        summary = {}
        for stage_name, st in stage_data.items():
            summary[stage_name] = {
                'invocations': st['count'],
                'total_duration_sec': round(st['total_duration_sec'], 3),
                'duration_share_pct': round((st['total_duration_sec'] / total_dur_all) * 100, 1),
                'critical_path_duration_sec': round(st['critical_path_duration_sec'], 3),
                'total_tokens': st['total_tokens'],
                'token_share_pct': round((st['total_tokens'] / total_tokens_all) * 100, 1),
                'cost_usd': round(st['cost_usd'], 4),
                'defects_introduced': st['defects_introduced'],
                'defects_detected': st['defects_detected'],
                'defects_repaired': st['defects_repaired'],
                'revisions_triggered': st['revisions_triggered'],
                'top_reasons': dict(sorted(st['reasons'].items(), key=lambda x: x[1], reverse=True)[:3])
            }
        return summary

    def compute_integration_gap(self, run_results: List[Dict]) -> float:
        """P(final external failure | all required nodes internally accepted)"""
        all_accepted_runs = [r for r in run_results if r.get('internal_gates_met', False)]
        if not all_accepted_runs:
            return 0.0
        failed_externally = sum(1 for r in all_accepted_runs if not r.get('verified_completion', False))
        return round(failed_externally / len(all_accepted_runs), 3)

    def compute_revision_yield_by_attempt(self) -> Dict[int, Dict]:
        """Computes verified repairs attributable to revision divided by revision cost per attempt."""
        attempts = defaultdict(lambda: {'cost_tokens': 0, 'repairs': 0, 'invocations': 0})
        for s in self.spans:
            if s.stage == DAFGStage.REVISION_INVALIDATION or s.decision == 'REVISE':
                ep = s.epoch
                attempts[ep]['invocations'] += 1
                attempts[ep]['cost_tokens'] += (s.input_tokens + s.output_tokens)
                if s.defect_repaired:
                    attempts[ep]['repairs'] += 1

        yield_by_attempt = {}
        for ep in sorted(attempts.keys()):
            dat = attempts[ep]
            yield_val = round(dat['repairs'] / (dat['cost_tokens'] / 1000), 3) if dat['cost_tokens'] > 0 else 0.0
            yield_by_attempt[ep] = {
                'invocations': dat['invocations'],
                'repairs': dat['repairs'],
                'cost_tokens': dat['cost_tokens'],
                'repair_yield_per_1k_tokens': yield_val,
                'marginal_success_rate': round(dat['repairs'] / dat['invocations'], 2) if dat['invocations'] > 0 else 0.0
            }
        return yield_by_attempt
