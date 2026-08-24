#!/usr/bin/env python3
import argparse, json
import numpy as np, pandas as pd
from server.poc_absorption.pressure_efficiency_edge import EdgeMapConfig, assign_pressure_efficiency_cells, cell_outcome_means, d_minus_b, classify_dev9

def self_test():
    rng=np.random.default_rng(20260824); rows=[]
    for s in ["day","night"]:
        for i in range(80):
            activity=float(rng.lognormal()); pressure=activity*(.45+.1*rng.random()); eff=float(rng.random()); future_eff=.08-.015*(activity>np.median([1.0]))+rng.normal(0,.02)
            rows.append((s,pressure,eff,future_eff))
    x=pd.DataFrame(rows,columns=["session","pressure","eff","future_eff"])
    x=assign_pressure_efficiency_cells(x,EdgeMapConfig("pressure","eff")); m=cell_outcome_means(x,["future_eff"]); contrast=float(d_minus_b(m).future_eff)
    verdict=classify_dev9(directional_pressure_supported=False,activity_adjusted_pressure_supported=False,buy_side_specific=False,efficiency_directional_edge=False)
    return {"schema_version":"POC_M6_DEV9_SELF_TEST_V1","events":len(x),"cells":sorted(x.edge_cell.unique().tolist()),"D_minus_B_future_eff":contrast,"verdict":verdict["verdict"],"pnl_calculated":False,"threshold_optimized":False,"all_pass":verdict["verdict"].startswith("M6_DEV9_") and set(x.edge_cell)=={"A","B","C","D"}}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if not a.self_test: raise SystemExit('use --self-test in CI')
    r=self_test(); print(json.dumps(r,indent=2)); raise SystemExit(0 if r['all_pass'] else 1)
if __name__=='__main__': main()
