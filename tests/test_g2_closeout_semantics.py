from server.g2_closeout import MR_CHAIN, BO_CHAIN, PARENTS, VALID_STATUSES, REACHABILITY_VERSION, CAUSAL_REPAIR_VERSION

def test_status_contract():
    assert VALID_STATUSES == {'EVALUATED','NOT_REACHED','NOT_APPLICABLE','TERMINAL'}
    assert REACHABILITY_VERSION.startswith('G2_NODE_REACHABILITY_')

def test_frozen_chain_parentage():
    for chain in (MR_CHAIN,BO_CHAIN):
        for i in range(1,len(chain)):
            assert PARENTS[chain[i]] == chain[i-1]

def test_common_registry_parentage():
    assert PARENTS['AUC_ATTEMPT']=='CTX_VALUE'
    assert PARENTS['AUC_EXTREME']=='AUC_ATTEMPT'

def test_causal_repair_is_bo_entry_scoped_versioned():
    assert CAUSAL_REPAIR_VERSION == 'G2_CAUSAL_ORDERING_AMENDMENT_001'
