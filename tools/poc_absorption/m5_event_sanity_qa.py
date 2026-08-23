#!/usr/bin/env python3
"""M5 Dev6 event-sanity QA: deterministic selection + replay/visual evidence validation."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import numpy as np,pandas as pd
REPO_ROOT=Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path: sys.path.insert(0,str(REPO_ROOT))
from server.poc_absorption.event_sanity import (SANITY_SAMPLING_VERSION,SanitySampleConfig,select_event_sanity_sample,validate_sanity_sample,validate_replay_ledger,validate_visual_manifest)

def _cfg(d):
 s=d.get('sampling',d);return SanitySampleConfig(per_category=int(s.get('per_category',25)),day_quota=int(s.get('day_quota',6)),night_quota=int(s.get('night_quota',19)),month_cap=int(s.get('month_cap',3)),min_observed_span_30m_seconds=int(s.get('min_observed_span_30m_seconds',1740)))

def synthetic():
 rows=[];base=pd.Timestamp('2024-01-02');kinds=['mfe','mae','bal','str','none']
 for i in range(120):
  kind=kinds[(i//24)%5];sess='day' if i%2==0 else 'night';d=base+pd.Timedelta(days=i);tr=int((d+pd.Timedelta(hours=9 if sess=='day' else 16)).timestamp())
  mfe,mae,eff,two,br,delay=(100,1,.5,.2,True,300) if kind=='mfe' else (1,100,.5,.2,True,400) if kind=='mae' else (5,5,.0,3,True,200) if kind=='bal' else (3,3,.4,.5,True,1) if kind=='str' else (.2,.2,.4,.1,False,np.nan)
  rows.append({'event_key':f'e{i:03d}','session':sess,'trading_day_int':int(d.timestamp()//86400),'trigger_sec':tr,'atr':5.0,'mfe_30m_atr':mfe,'mae_30m_atr':mae,'balance_5m_eff':eff,'balance_5m_two_sided_min_atr':two,'break_30m':br,'break_second_approx':np.nan if not br else tr+delay,'sanity_full_30m':True})
 return pd.DataFrame(rows)

def self_test():
 cfg=SanitySampleConfig(per_category=2,day_quota=1,night_quota=1,month_cap=2,min_observed_span_30m_seconds=1740);s=select_event_sanity_sample(synthetic(),cfg);h=s.sanity_sample_event_ids_sha256.iloc[0]
 led=pd.DataFrame({'event_key':s.event_key,'pass':True,'mismatch_fields':'','observation_span_seconds':1800,'sanity_sampling_version':SANITY_SAMPLING_VERSION,'sanity_sample_event_ids_sha256':h})
 cats=[{'sanity_category':c,'panels_reviewed':2,'visual_mismatches':0,'visual_verdict':'PASS'} for c in ['strong_mfe','strong_mae','high_balance','structure_reversal','no_reaction']]
 vis={'sampling_version':SANITY_SAMPLING_VERSION,'sample_event_ids_sha256':h,'total_panels_reviewed':10,'total_visual_mismatches':0,'categories':cats,'all_pass':True}
 a=validate_sanity_sample(s,cfg);b=validate_replay_ledger(s,led,cfg);c=validate_visual_manifest(s,vis,cfg);ok=a['all_pass'] and b['all_pass'] and c['all_pass']
 return {'schema_version':'POC_M5_DEV6_SELF_TEST_V1','sampling_version':SANITY_SAMPLING_VERSION,'events':len(s),'categories':5,'raw_replay_passed':b['passed'],'visual_panels':c['panels'],'thresholds_defined':False,'pnl_calculated':False,'edge_claimed':False,'all_pass':bool(ok)}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--config',type=Path,default=Path('config/poc_absorption/m5_event_sanity_v1.json'));ap.add_argument('--outcomes',type=Path);ap.add_argument('--selected-evidence',type=Path);ap.add_argument('--ledger',type=Path);ap.add_argument('--visual-manifest',type=Path);ap.add_argument('--output',type=Path);a=ap.parse_args()
 if a.self_test:r=self_test()
 else:
  cfgd=json.loads(a.config.read_text());cfg=_cfg(cfgd)
  if a.outcomes:
   s=select_event_sanity_sample(pd.read_parquet(a.outcomes),cfg)
   if a.selected_evidence:
    e=pd.read_csv(a.selected_evidence);same=s.event_key.astype(str).tolist()==e.event_key.astype(str).tolist()
    if not same: raise SystemExit('selected-evidence event order/hash drift')
  elif a.selected_evidence:s=pd.read_csv(a.selected_evidence)
  else:ap.error('--outcomes or --selected-evidence required')
  sample=validate_sanity_sample(s,cfg);replay=None;visual=None
  if a.ledger: replay=validate_replay_ledger(s,pd.read_csv(a.ledger),cfg)
  if a.visual_manifest: visual=validate_visual_manifest(s,json.loads(a.visual_manifest.read_text()),cfg)
  ok=sample['all_pass'] and (replay is None or replay['all_pass']) and (visual is None or visual['all_pass'])
  r={'schema_version':'POC_M5_DEV6_QA_V1','sampling_version':SANITY_SAMPLING_VERSION,'sample':sample,'raw_replay':replay,'visual_review':visual,'thresholds_defined':False,'pnl_calculated':False,'edge_claimed':False,'all_pass':bool(ok)}
 txt=json.dumps(r,ensure_ascii=False,indent=2,default=str);print(txt)
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(txt+'\n')
 raise SystemExit(0 if r['all_pass'] else 2)
if __name__=='__main__':main()
