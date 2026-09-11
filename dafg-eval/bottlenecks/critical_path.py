"""Critical path reconstruction and scheduler bottleneck analyzer."""

from typing import Dict, List
from dafg_eval.telemetry.spans import TraceSpan

class CriticalPathAnalyzer:
    def __init__(self, spans: List[TraceSpan]):
        self.spans = spans

    def analyze(self) -> Dict:
        critical_spans = [s for s in self.spans if s.is_critical_path]
        total_crit_service_sec = sum(s.duration_sec for s in critical_spans)
        total_crit_queue_sec = sum(s.queue_ms / 1000.0 for s in critical_spans)
        
        # Breakdown by stage on critical path
        stage_crit_time = {}
        for s in critical_spans:
            stage_crit_time[s.stage] = stage_crit_time.get(s.stage, 0.0) + s.duration_sec

        top_stages = sorted(stage_crit_time.items(), key=lambda x: x[1], reverse=True)

        return {
            'total_critical_path_sec': round(total_crit_service_sec + total_crit_queue_sec, 3),
            'critical_service_time_sec': round(total_crit_service_sec, 3),
            'critical_queue_wait_sec': round(total_crit_queue_sec, 3),
            'queue_to_service_ratio': round(total_crit_queue_sec / total_crit_service_sec, 3) if total_crit_service_sec > 0 else 0.0,
            'top_critical_path_stages': [{ 'stage': st, 'duration_sec': round(dur, 3), 'share_pct': round((dur / total_crit_service_sec)*100, 1) if total_crit_service_sec > 0 else 0.0 } for st, dur in top_stages]
        }
