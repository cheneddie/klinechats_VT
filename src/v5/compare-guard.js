(()=>{
  const originalFetch=window.fetch.bind(window);
  let latest=null;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));

  function render(){
    if(!location.hash.startsWith('#/compare')||!latest)return;
    const host=document.querySelector('#cmpBody');
    if(!host||host.dataset.compareGuardRendered==='1')return;
    const gate=latest.comparability||{};
    const status=gate.status||'INSUFFICIENT';
    const ok=status==='COMPARABLE';
    const checks=(gate.checks||[]).map(x=>`<div class="check"><span>${esc(x.name)}</span><b class="${x.passed?'yes':'no'}">${x.passed?'PASS':'BLOCK'}</b></div>`).join('');
    const warnings=(gate.warnings||[]).length?`<p class="muted">Warnings: ${esc(gate.warnings.join(', '))}</p>`:'';
    const banner=`<section class="sl-card compare-gate" data-compare-status="${esc(status)}"><h2>Comparability Gate ${ok?'<span class="pill yes">COMPARABLE</span>':'<span class="pill no">BLOCKED</span>'}</h2>${checks}${warnings}<p class="muted">${ok?'資料、執行假設與 Portfolio Policy 一致；績效差異才可進一步解讀。':'比較被阻擋：以下數值不可直接解讀為策略優劣，先修正不一致的資料或成交假設。'}</p></section>`;
    if(ok){host.insertAdjacentHTML('afterbegin',banner)}else{host.innerHTML=banner}
    host.dataset.compareGuardRendered='1';
  }

  window.fetch=async(input,init={})=>{
    const url=typeof input==='string'?input:String(input?.url||'');
    let next=input;
    if(url.includes('/v5/strategy-lab/compare?backtest_run_ids='))next=url.replace('/v5/strategy-lab/compare?','/v5/strategy-lab/compare-governed?');
    const response=await originalFetch(next,init);
    if(String(next).includes('/v5/strategy-lab/compare-governed?')&&response.ok){
      try{latest=await response.clone().json();setTimeout(render,0)}catch{}
    }
    return response;
  };

  new MutationObserver(render).observe(document.documentElement,{subtree:true,childList:true});
  addEventListener('hashchange',()=>{latest=null});
  window.StrategyLabCompareGuard={get:()=>latest};
})();
