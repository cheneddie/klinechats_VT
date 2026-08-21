from __future__ import annotations

def assert_decision_parity(a:list[dict],b:list[dict],keys=("signal_time","threshold","highvol_state","entry","stop","exit")):
    if len(a)!=len(b): raise AssertionError(f"decision count differs: {len(a)} != {len(b)}")
    for i,(x,y) in enumerate(zip(a,b)):
        for k in keys:
            if x.get(k)!=y.get(k): raise AssertionError(f"parity mismatch i={i} key={k}: {x.get(k)!r}!={y.get(k)!r}")
    return True
