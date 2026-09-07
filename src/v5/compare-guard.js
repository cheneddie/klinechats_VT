(()=>{
  const originalFetch=window.fetch.bind(window);
  let latest=null;
  let seq=0;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function tableRunIds(host){
    return [...host.querySelectorAll('table tbody tr')]
      .map(row=>String(row.cells?.[0]?.textContent||'').trim())
      .filter(Boolean);
  }

  function render(){
    if(!location.hash.startsWith('#/compare')||!latest)return;
    const host=document.querySelector('#cmpBody');
    if(!host)return;
    const table=host.querySelector('table');
    if(!table)return;

    // A governed response is available before the legacy Compare handler has
    // necessarily replaced the previous table. Never apply the gate to stale
    // DOM: wait until the table rows correspond to this response's run IDs.
    const expected=(latest.data.items||[]).map(x=>String(x?.run?.backtest_run_id||'')).filter(Boolean);
    const actual=tableRunIds(host);
    if(expected.length&&(
      actual.length!==expected.length||expected.some((id,i)=>actual[i]!==id)
    ))return;

    if(host.dataset.compareGuardToken===latest.token&&host.querySelector(`[data-compare-token="${latest.token}"]`))return;
    const gate=latest.data.comparability||{};
    const status=gate.status||'INSUFFICIENT';
    const ok=status==='COMPARABLE';
    const checks=(gate.checks||[]).map(x=>`<div class="check"><span>${esc(x.name)}</span><b class="${x.passed?'yes':'no'}">${x.passed?'PASS':'BLOCK'}</b></div>`).join('');
    const warnings=(gate.warnings||[]).length?`<p class="muted">Warnings: ${esc(gate.warnings.join(', '))}</p>`:'';
    const banner=`<section class="sl-card compare-gate" data-compare-status="${esc(status)}" data-compare-token="${latest.token}"><h2>Comparability Gate ${ok?'<span class="pill yes">COMPARABLE</span>':'<span class="pill no">BLOCKED</span>'}</h2>${checks}${warnings}<p class="muted">${ok?'資料、執行假設與 Portfolio Policy 一致；績效差異才可進一步解讀。':'比較被阻擋：以下數值不可直接解讀為策略優劣，先修正不一致的資料或成交假設。'}</p></section>`;
    host.querySelectorAll('.compare-gate').forEach(x=>x.remove());
    if(ok){host.insertAdjacentHTML('afterbegin',banner)}else{host.innerHTML=banner}
    host.dataset.compareGuardToken=latest.token;
  }

  window.fetch=async(input,init={})=>{
    const url=typeof input==='string'?input:String(input?.url||'');
    let next=input;
    if(url.includes('/v5/strategy-lab/compare?backtest_run_ids='))next=url.replace('/v5/strategy-lab/compare?','/v5/strategy-lab/compare-governed?');
    const response=await originalFetch(next,init);
    if(String(next).includes('/v5/strategy-lab/compare-governed?')&&response.ok){
      try{
        latest={token:String(++seq),data:await response.clone().json()};
        // Do not render here. The core Compare handler has not necessarily
        // committed its new table yet. MutationObserver below applies the gate
        // only after the response-specific rows reach the DOM.
      }catch{}
    }
    return response;
  };

  new MutationObserver(render).observe(document.documentElement,{subtree:true,childList:true});
  addEventListener('hashchange',()=>{latest=null});
  window.StrategyLabCompareGuard={get:()=>latest?.data||null};
})();
