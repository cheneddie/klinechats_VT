from __future__ import annotations
import argparse,json
from pathlib import Path
from .cache import build_second_cache
from .backtest import run_baseline,BacktestSpec
from .golden import validate_golden

def main():
    p=argparse.ArgumentParser("mtx_reversal_v2"); s=p.add_subparsers(dest="cmd",required=True)
    b=s.add_parser("build-cache"); b.add_argument("input",type=Path); b.add_argument("out",type=Path)
    r=s.add_parser("reproduce-baseline"); r.add_argument("cache",type=Path); r.add_argument("out",type=Path)
    g=s.add_parser("golden-check"); g.add_argument("trades",type=Path); g.add_argument("golden",type=Path)
    a=p.parse_args()
    if a.cmd=="build-cache": print(json.dumps(build_second_cache(a.input,a.out),indent=2))
    elif a.cmd=="reproduce-baseline":
        t=run_baseline(a.cache,BacktestSpec()); t.to_csv(a.out,index=False); print({"trades":len(t),"net2":float(t.net.sum())})
    else: print(json.dumps(validate_golden(a.trades,a.golden),indent=2))
if __name__=="__main__": main()
