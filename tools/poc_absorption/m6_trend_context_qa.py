#!/usr/bin/env python3
import argparse,json,numpy as np,pandas as pd
from server.poc_absorption.trend_context import label_context,bh_fdr,classify_dev10

def self_test():
 f=pd.DataFrame({'session':['day']*6+['night']*6,'slope_atr_24':[-.2,.1,.2,.3,.4,.5,-.1,.1,.2,.3,.4,.5],'channel_width_atr_24':[1,2,3,4,5,6,10,20,30,40,50,60]})
 x=label_context(f); p=np.linspace(.2,.9,128); q=bh_fdr(p); r=classify_dev10(global_positive=bool((q<=.1).any()),context_directional_increment=False,conditional_increment=False)
 return {'schema_version':'POC_M6_DEV10_SELF_TEST_V1','events':len(x),'rising':int(x.rising_context.sum()),'rising_broad':int(x.rising_broad_context.sum()),'tests_in_global_family':128,'global_positive':bool((q<=.1).any()),'verdict':r['verdict'],'pnl_calculated':False,'threshold_optimized':False,'all_pass':r['verdict'].startswith('M6_DEV10_')}
def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');z=a.parse_args();
 if not z.self_test: raise SystemExit('use --self-test')
 r=self_test();print(json.dumps(r,indent=2));raise SystemExit(0 if r['all_pass'] else 1)
if __name__=='__main__': main()
