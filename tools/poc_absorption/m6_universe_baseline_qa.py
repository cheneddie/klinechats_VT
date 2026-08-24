#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from server.poc_absorption.universe_baseline import *

def synth():
 rows=[]
 for i in range(240):
  # alternating clustered days; deliberately near-neutral
  d=19724+i//12; sess='day' if i%2==0 else 'night'; direction=((i//2)%2==0); m=1.2 if direction else .8; a=.8 if direction else 1.2
  rows.append({'event_key':f'e{i}','session':sess,'trading_day_int':d,'atr':5+(i%3),'mfe_30m_atr':m,'mae_30m_atr':a,'break_30m':i%2==0,'balance_5m_eff':.05,'balance_5m_two_sided_min_atr':.4,'sanity_full_30m':i%19!=0})
 return pd.DataFrame(rows)

def analyze(frame,cfg):
 x=prepare_baseline(frame); primary=x.loc[x.sanity_full_30m.astype(bool)].reset_index(drop=True); out={'schema_version':BASELINE_SCHEMA_VERSION,'source_events':len(x),'primary_events':len(primary),'all_episodes':baseline_metrics(x),'primary_full30':baseline_metrics(primary),'sessions':{},'bootstrap':{},'monthly_signs':{},'predictors_used':[],'pnl_calculated':False,'thresholds_defined':False,'best_horizon_selected':False,'edge_claimed':False}
 b=cfg['bootstrap']; seed=int(b['seed'])
 for i,sess in enumerate(('day','night')):
  z=primary[primary.session.eq(sess)].reset_index(drop=True); out['sessions'][sess]=baseline_metrics(z); out['bootstrap'][sess]={'episode_resample':bootstrap_ci(z,mode='episode',n_resamples=int(b['episode_resamples_session']),seed=seed+i),'trading_day_cluster':bootstrap_ci(z,mode='trading_day',n_resamples=int(b['trading_day_resamples_session']),seed=seed+10+i)}
 out['bootstrap']['pooled']={'episode_resample':bootstrap_ci(primary,mode='episode',n_resamples=int(b['episode_resamples_pooled']),seed=seed+20),'trading_day_cluster':bootstrap_ci(primary,mode='trading_day',n_resamples=int(b['trading_day_resamples_pooled']),seed=seed+21)}
 month=monthly_baseline(primary)
 for sess,g in month.groupby('session'):
  out['monthly_signs'][sess]={'months':len(g),'mean_asym_positive_months':int((g.paired_asym_mean_atr>0).sum()),'mean_asym_negative_months':int((g.paired_asym_mean_atr<0).sum()),'p_mfe_gt_mae_above_50pct_months':int((g.p_mfe_gt_mae>.5).sum()),'p_mfe_gt_mae_below_50pct_months':int((g.p_mfe_gt_mae<.5).sum())}
 out['directional_baseline_verdict']=directional_baseline_verdict(out['bootstrap']['pooled']['trading_day_cluster']);out['all_pass']=out['directional_baseline_verdict']==BASELINE_VERDICT and out['source_events']>out['primary_events']>0
 return out,month

def self_test():
 cfg={'bootstrap':{'episode_resamples_session':100,'trading_day_resamples_session':100,'episode_resamples_pooled':100,'trading_day_resamples_pooled':100,'seed':7}};r,_=analyze(synth(),cfg);return {'schema_version':'POC_M6_DEV7_SELF_TEST_V1','events':r['source_events'],'primary_events':r['primary_events'],'directional_baseline_verdict':r['directional_baseline_verdict'],'predictors_used':r['predictors_used'],'pnl_calculated':False,'all_pass':r['all_pass']}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--input',type=Path);ap.add_argument('--config',type=Path,default=Path('config/poc_absorption/m6_dev7_universe_baseline_v1.json'));ap.add_argument('--output',type=Path);ap.add_argument('--monthly-output',type=Path);a=ap.parse_args()
 if a.self_test:r=self_test()
 else:
  if not a.input:ap.error('--input required unless --self-test')
  cfg=json.loads(a.config.read_text());f=pd.read_parquet(a.input);r,m=analyze(f,cfg)
  if int(cfg.get('expected_episodes',len(f)))!=len(f):raise SystemExit('episode count drift')
  if a.monthly_output:a.monthly_output.parent.mkdir(parents=True,exist_ok=True);m.to_csv(a.monthly_output,index=False)
 txt=json.dumps(r,indent=2,ensure_ascii=False);print(txt)
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(txt+'\n')
 raise SystemExit(0 if r['all_pass'] else 2)
if __name__=='__main__':main()
