#!/usr/bin/env python3
import argparse,json,numpy as np,pandas as pd
from server.poc_absorption.poc_dose_response import *
def self_test():
 r=pd.DataFrame({'p_cluster':[.005]+[.2]*137,'slope':[.04]+[.01]*137});g=global_multiplicity_verdict(r)
 return {'schema_version':'POC_M6_DEV8_SELF_TEST_V1','tests_in_global_family':g['tests'],'single_local_p':.005,'single_global_q':float(g['q_values'][0]),'global_positive':g['any_positive_global_fdr'],'verdict':classify_dev8(primary_30m_present=False,short_15m_within_horizon_present=True,global_fdr_present=g['any_positive_global_fdr']),'pnl_calculated':False,'threshold_optimized':False,'all_pass':g['tests']==138 and not g['any_positive_global_fdr']}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');x=a.parse_args();r=self_test();print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_pass'] else 1)
