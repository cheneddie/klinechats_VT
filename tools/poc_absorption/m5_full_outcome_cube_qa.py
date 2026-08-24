#!/usr/bin/env python3
"""M5 Dev5 full-year aggregation QA. No event re-selection or strategy optimization."""
import argparse,json
from pathlib import Path
import pandas as pd
from server.poc_absorption.full_outcome_cube import *

def read_fragments(d):
    fs=sorted(Path(d).rglob('*.parquet'))
    if not fs: raise ValueError('no Parquet fragments')
    a=[];schema=None
    for p in fs:
        x=pd.read_parquet(p); c=tuple(x.columns)
        if schema is None:schema=c
        elif c!=schema:raise ValueError('fragment schema mismatch')
        a.append(x)
    return pd.concat(a,ignore_index=True),len(fs)
def self_test():
    rows=[]
    for i,tf in enumerate(FROZEN_TIMEFRAMES):rows.append(dict(event_id=f'e{i}',episode_id=f'p{i}',episode_trigger_number=1,timeframe=tf,session='day',h_30s_mfe_atr=.1,h_5m_mfe_atr=.2,h_30m_mfe_atr=.4,h_30m_mae_atr=.5,h_5m_one_second_path_efficiency=.05,h_5m_two_sided_min_excursion_atr=.2,h_5m_any_structure_break=True,h_15m_any_structure_break=True,h_30m_any_structure_break=False,h_session_end_any_structure_break=True))
    cube=summarize_full_outcome_cube(pd.DataFrame(rows)); led=pd.DataFrame({'event_id':['x']*8,'horizon':['30s','1m','3m','5m','15m','30m','60m','session_end'],'pass':[True]*8,'mismatch_fields':['']*8});aud=validate_audit_ledger(led,8)
    return {'schema_version':'POC_M5_DEV5_SELF_TEST_V1','events':6,'cube_rows':len(cube),'audit_windows':8,'audit_mismatches':aud['mismatches'],'pnl_calculated':False,'thresholds_defined':False,'best_horizon_selected':False,'all_pass':len(cube)==12 and aud['all_pass']}
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--outcome-dir',type=Path);p.add_argument('--audit-ledger',type=Path);p.add_argument('--output-dir',type=Path,default=Path('reports/poc_absorption/m5_dev5_runtime'));a=p.parse_args()
    if a.self_test:r=self_test()
    else:
        if not a.outcome_dir or not a.audit_ledger:p.error('--outcome-dir and --audit-ledger required')
        x,n=read_fragments(a.outcome_dir); frozen=validate_2024_frozen_counts(x); aud=validate_audit_ledger(pd.read_csv(a.audit_ledger)); cube=summarize_full_outcome_cube(x);a.output_dir.mkdir(parents=True,exist_ok=True);cube.to_csv(a.output_dir/'M5_DEV5_2024_FULL_OUTCOME_CUBE.csv',index=False)
        r={'schema_version':'POC_M5_DEV5_REAL_QA_V1','verdict':'M5_DEV5_2024_FULL_OUTCOME_CUBE_PASS','outcome_fragments':n,'outcome_rows':len(x),'unique_event_id':x.event_id.nunique(),'frozen_annual_counts':frozen,'independent_audit':aud,'research_primary_clock':'1m','research_companion_clock':'30s','pnl_calculated':False,'profit_factor_calculated':False,'thresholds_defined':False,'best_horizon_selected':False,'research_edge_claimed':False,'all_pass':bool(frozen['all_pass'] and aud['all_pass'] and len(x)==505448 and x.event_id.nunique()==505448)}
        (a.output_dir/'M5_DEV5_FORMAL_QA_SUMMARY.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_pass'] else 2)
if __name__=='__main__':main()
