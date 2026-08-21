import json
from pathlib import Path

def test_golden_baseline_is_frozen():
    p=Path(__file__).parents[1]/"artifacts/run_manifests/GOLDEN_BASELINE.json"
    d=json.loads(p.read_text())
    assert d["baseline_commit"]=="2cbaf76971b8ba1a8cac0ac38e23a860d7f64e61"
    assert d["expected"]["trades"]==3655
    assert d["expected"]["net2_total_points"]==5104.0
