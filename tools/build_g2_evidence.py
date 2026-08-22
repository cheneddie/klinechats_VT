from __future__ import annotations
import argparse,hashlib,json,platform,shutil,sys
from pathlib import Path
import pandas as pd,pyarrow as pa,numpy as np
ROOT=Path(__file__).resolve().parents[1]
def fsha(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def dump(p,o):Path(p).write_text(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--run-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--source',required=True);a=ap.parse_args();run=Path(a.run_dir);out=Path(a.out)
 gate=json.load(open(run/'g2_audit_gate.json'))
 if gate.get('status')!='PASS' or gate.get('pass') is not True:raise SystemExit('REFUSE_TO_PACKAGE_G2_NOT_PASS')
 if out.exists():shutil.rmtree(out)
 out.mkdir(parents=True)
 names=['session_eligibility_audit.json','migration_regression.json','strategy_semantics_regression.json','relaxed_universe_regression.json','logical_trace_audit.json','blocker_lineage_audit.json','physical_truth_audit.json','causal_ordering_audit.json','funnel.json','first_failure_funnel.json','conditional_node_conversion.json','conversion_collapse.json','targeted_qa_manifest.json','targeted_qa_results.json','g2_audit_gate.json']
 for n in names:shutil.copy2(run/n,out/n)
 shutil.copy2(ROOT/'config/research/g2_node_reachability_v1.json',out/'reachability_policy.json')
 shutil.copy2(ROOT/'config/research/g2_causal_ordering_amendment_001.json',out/'causal_ordering_amendment_001.json')
 src=Path(a.source)
 manifest={
  'campaign_id':'FABIO_REAL_EVIDENCE_V1_20260821','gate':'G2_CAUSAL_SIGNAL_TRUTH','status':'PASS','source_role':'2025_PARTIAL_YEAR_DISCOVERY','source_file':src.name,'source_sha256':fsha(src),'source_window':'2025-01-02 through 2025-12-19','observed_sessions':236,'eligible_scan_sessions':223,
  'baseline_methodology_commit':'53dbd9450922cfd24385e9f98b116d0d912e21e5','release_commit':'THIS_COMMIT_CONTAINING_MANIFEST','reachability_policy':'G2_NODE_REACHABILITY_V1_20260823','causal_repair_policy':'G2_CAUSAL_ORDERING_AMENDMENT_001','coverage_policy':'TAIFEX_SESSION_CALENDAR_V2','calendar_version':'TAIFEX_REGULAR_SESSION_V1_20260821',
  'implementation_sha256':{str(p.relative_to(ROOT)):fsha(p) for p in [ROOT/'server/g2_closeout.py',ROOT/'tools/run_g2_closeout.py',ROOT/'tools/run_g2_shard.py',ROOT/'tools/audit_g2_closeout.py',ROOT/'tools/build_g2_evidence.py',ROOT/'config/research/g2_node_reachability_v1.json',ROOT/'config/research/g2_causal_ordering_amendment_001.json']},
  'runtime':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,'pyarrow':pa.__version__},
  'canonical_hashing':json.load(open(run/'migration_regression.json')).get('canonical_serialization'),
  'future_outcomes':{'mfe':False,'mae':False,'pf':False,'bootstrap':False,'fdr':False,'edge_classification':False},
  'validation_holdout_governance':{'2024':'RESERVED_NOT_OPENED_FOR_STRATEGY_VALIDATION','2026':'SEALED_NO_STRATEGY_SIGNALS_OR_OUTCOMES'},
 }
 dump(out/'g2_run_manifest.json',manifest)
 readme='''# G2 Causal Signal Truth — 2025 Partial-Year Discovery\n\nStatus: **PASS** only if `g2_audit_gate.json` says PASS.\n\nThis bundle contains causal-signal truth evidence only. It does **not** contain MFE/MAE, PF, bootstrap/FDR, node-edge classification, 2024 strategy validation, or 2026 strategy outcomes.\n\nKey semantics: `EVALUATED` means the node was actually asked and answered YES/NO; `NOT_REACHED` means an upstream strict prerequisite failed first; `NOT_APPLICABLE` means the node is outside the current branch; `TERMINAL` ends the decision flow. G3 node-edge comparisons are restricted to the `EVALUATED` universe.\n\nThe 2025 source is partial-year Discovery: 236 observed sessions from 2025-01-02 through 2025-12-19, of which 223 are scanner-eligible after the first observed session and 12 frozen roll-blackout sessions are excluded.\n\n`G2_CAUSAL_ORDERING_AMENDMENT_001` was frozen before any future-path outcome/PF inspection and repairs only BO strict entries whose legacy entry decision preceded completion of required causal gates.\n'''
 (out/'README.md').write_text(readme,encoding='utf-8')
 files=sorted(p for p in out.iterdir() if p.is_file() and p.name!='sha256.txt');(out/'sha256.txt').write_text('\n'.join(f'{fsha(p)}  {p.name}' for p in files)+'\n',encoding='utf-8')
 print(json.dumps({'out':str(out),'files':len(list(out.iterdir())),'status':'PASS'},indent=2))
if __name__=='__main__':main()
