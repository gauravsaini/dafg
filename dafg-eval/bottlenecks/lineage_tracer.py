"""Artifact lineage and failure origin attribution tracer."""

from typing import Dict, List
from collections import defaultdict
from dafg_eval.telemetry.spans import TraceSpan, DAFGStage

class LineageTracer:
    def __init__(self, spans: List[TraceSpan]):
        self.spans = spans

    def trace_failure_origins(self) -> Dict:
        """Traces: Origin Stage -> Escape Point -> Detection Point -> Downstream Wasted Tokens"""
        origin_escapes = defaultdict(lambda: {'occurrences': 0, 'wasted_tokens': 0, 'escape_points': defaultdict(int), 'detection_points': defaultdict(int)})
        
        # Group spans by run_id
        runs = defaultdict(list)
        for s in self.spans:
            runs[s.run_id].append(s)

        for run_id, run_spans in runs.items():
            introduced_span = None
            for s in run_spans:
                if s.defect_introduced and introduced_span is None:
                    introduced_span = s
                
            if introduced_span:
                # Find detection span
                detect_span = None
                for s in run_spans:
                    if s.defect_detected or s.decision in ['REVISE', 'INVALIDATE', 'BLOCK']:
                        detect_span = s
                        break
                
                # Escape point is the verification stage immediately following introduction that failed to catch it
                escape_stage = DAFGStage.VERIFICATION
                detect_stage = detect_span.stage if detect_span else DAFGStage.DELIVERY
                
                # Wasted downstream tokens = all tokens between introduction and detection
                wasted = sum(s.input_tokens + s.output_tokens for s in run_spans if s.started_at >= introduced_span.started_at)
                
                rec = origin_escapes[introduced_span.stage]
                rec['occurrences'] += 1
                rec['wasted_tokens'] += wasted
                rec['escape_points'][escape_stage] += 1
                rec['detection_points'][detect_stage] += 1

        summary = {}
        for orig, dat in origin_escapes.items():
            summary[orig] = {
                'occurrences': dat['occurrences'],
                'total_wasted_tokens': dat['wasted_tokens'],
                'avg_wasted_tokens_per_incident': int(dat['wasted_tokens'] / dat['occurrences']) if dat['occurrences'] > 0 else 0,
                'top_escape_points': dict(dat['escape_points']),
                'top_detection_points': dict(dat['detection_points'])
            }
        return summary
