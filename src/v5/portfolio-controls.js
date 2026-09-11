(()=>{
  const KEY='strategyLabPortfolioPolicyV1';
  const DEFAULT={mode:'INDEPENDENT_EVENT',overlap_policy:'ALLOW',max_open_positions:1,reentry_cooldown_seconds:0,fixed_quantity:1,force_flat_time:null};
  const originalFetch=window.fetch.bind(window);
  const clone=x=>JSON.parse(JSON.stringify(x));

  function normalize(raw){
    const p={...DEFAULT,...(raw||{})};
    p.mode=String(p.mode||DEFAULT.mode).toUpperCase();
    if(p.mode==='SINGLE_POSITION'){
      p.overlap_policy='SKIP_WHILE_OPEN';
      p.max_open_positions=1;
    }else{
      p.mode='INDEPENDENT_EVENT';
      p.overlap_policy='ALLOW';
      p.max_open_positions=1;
    }
    p.reentry_cooldown_seconds=Math.max(0,parseInt(p.reentry_cooldown_seconds||0,10)||0);
    p.fixed_quantity=Math.max(0.000001,Number(p.fixed_quantity||1));
    const flat=String(p.force_flat_time||'').trim();
    p.force_flat_time=flat||null;
    return p;
  }

  function load(){
    try{return normalize(JSON.parse(localStorage.getItem(KEY)||'null'))}catch{return clone(DEFAULT)}
  }
  function save(p){const v=normalize(p);localStorage.setItem(KEY,JSON.stringify(v));return v}
  let policy=save(load());

  function policyHashLabel(){
    const raw=JSON.stringify(policy);
    let h=2166136261;
    for(let i=0;i<raw.length;i++){h^=raw.charCodeAt(i);h=Math.imul(h,16777619)}
    return (h>>>0).toString(16).padStart(8,'0');
  }

  function markup(scope){
    const single=policy.mode==='SINGLE_POSITION';
    return `<section class="sl-card portfolio-policy-card" data-portfolio-scope="${scope}">
      <h2>Portfolio Execution Policy <span class="pill ${single?'yes':'na'}">${single?'SINGLE POSITION':'INDEPENDENT'}</span></h2>
      <p class="muted">這是成交仲裁假設，不會改動 causal event universe。正式 Candidate 會凍結 policy hash，Discovery / Validation / Final Holdout 必須一致。</p>
      <div class="params">
        <label>Position mode
          <select data-pf="mode">
            <option value="INDEPENDENT_EVENT" ${!single?'selected':''}>INDEPENDENT_EVENT（保留舊行為）</option>
            <option value="SINGLE_POSITION" ${single?'selected':''}>SINGLE_POSITION（持倉中跳過新訊號）</option>
          </select>
        </label>
        <label>Overlap policy<input data-pf="overlap_policy" disabled value="${single?'SKIP_WHILE_OPEN':'ALLOW'}"></label>
        <label>Max open positions<input data-pf="max_open_positions" disabled type="number" value="1"></label>
        <label>Re-entry cooldown (sec)<input data-pf="reentry_cooldown_seconds" type="number" min="0" step="1" value="${policy.reentry_cooldown_seconds}"></label>
        <label>Fixed quantity<input data-pf="fixed_quantity" type="number" min="0.000001" step="1" value="${policy.fixed_quantity}"></label>
        <label>Force flat clock<input data-pf="force_flat_time" type="time" step="1" value="${policy.force_flat_time||''}"></label>
      </div>
      <div class="check"><span>Execution-assumption fingerprint</span><code data-pf-hash>${policyHashLabel()}</code></div>
      <div class="check"><span>Production realism</span><b class="${single?'yes':'no'}">${single?'single-position arbitration ON':'independent events may overlap'}</b></div>
    </section>`;
  }

  function syncFrom(card){
    const get=k=>card.querySelector(`[data-pf="${k}"]`)?.value;
    policy=save({
      mode:get('mode'),
      reentry_cooldown_seconds:get('reentry_cooldown_seconds'),
      fixed_quantity:get('fixed_quantity'),
      force_flat_time:get('force_flat_time'),
    });
    document.querySelectorAll('.portfolio-policy-card').forEach(c=>{
      if(c!==card)c.outerHTML=markup(c.dataset.portfolioScope||'shared');
    });
    const mode=card.querySelector('[data-pf="mode"]');
    const overlap=card.querySelector('[data-pf="overlap_policy"]');
    if(overlap)overlap.value=policy.mode==='SINGLE_POSITION'?'SKIP_WHILE_OPEN':'ALLOW';
    card.querySelector('[data-pf-hash]').textContent=policyHashLabel();
    const pill=card.querySelector('.pill');
    if(pill){pill.textContent=policy.mode==='SINGLE_POSITION'?'SINGLE POSITION':'INDEPENDENT';pill.className=`pill ${policy.mode==='SINGLE_POSITION'?'yes':'na'}`}
    const realism=card.querySelector('.check:last-child b');
    if(realism){realism.textContent=policy.mode==='SINGLE_POSITION'?'single-position arbitration ON':'independent events may overlap';realism.className=policy.mode==='SINGLE_POSITION'?'yes':'no'}
    return policy;
  }

  function bind(card){
    card.querySelectorAll('[data-pf]').forEach(el=>{
      el.addEventListener('change',()=>{
        const oldMode=policy.mode;
        syncFrom(card);
        if(el.dataset.pf==='mode'&&oldMode!==policy.mode){
          const scope=card.dataset.portfolioScope||'shared';
          card.outerHTML=markup(scope);
          const fresh=document.querySelector(`[data-portfolio-scope="${scope}"]`);
          if(fresh)bind(fresh);
        }
      });
    });
  }

  function inject(){
    const route=(location.hash.match(/^#\/([^/?]+)/)||[])[1]||'library';
    const specs={
      backtest:{anchor:'#btRun',scope:'backtest'},
      optimize:{anchor:'#optRun',scope:'optimize'},
      candidates:{anchor:'#candFreeze',scope:'candidate'},
    };
    const spec=specs[route];
    if(!spec||document.querySelector(`[data-portfolio-scope="${spec.scope}"]`))return;
    const anchor=document.querySelector(spec.anchor);
    if(!anchor)return;
    const holder=document.createElement('div');
    holder.innerHTML=markup(spec.scope);
    const card=holder.firstElementChild;
    const target=anchor.closest('.sl-card')||anchor.parentElement;
    target.insertAdjacentElement('afterend',card);
    bind(card);
  }

  function withPolicy(body){
    const out=clone(body);
    if(out?.job_type==='BACKTEST'||out?.job_type==='OPTIMIZATION'){
      out.payload=out.payload||{};
      out.payload.portfolio_policy=clone(policy);
      return out;
    }
    if(out?.strategy_key&&(out?.research_run_id||out?.search_space||out?.parameters)){
      out.portfolio_policy=clone(policy);
    }
    return out;
  }

  window.fetch=async(input,init={})=>{
    try{
      const method=String(init?.method||'GET').toUpperCase();
      const url=typeof input==='string'?input:String(input?.url||'');
      if(method==='POST'&&init?.body&&(/\/v5\/strategy-lab\/(jobs|backtests|optimizations|candidates)(?:$|\?)/).test(url)&&!url.includes('/evaluate')){
        const parsed=JSON.parse(String(init.body));
        const next=withPolicy(parsed);
        init={...init,body:JSON.stringify(next)};
      }
    }catch(err){console.error('portfolio-policy-request',err)}
    return originalFetch(input,init);
  };

  const observer=new MutationObserver(()=>inject());
  observer.observe(document.documentElement,{subtree:true,childList:true});
  window.addEventListener('hashchange',()=>setTimeout(inject,0));
  setTimeout(inject,0);

  window.StrategyLabPortfolio={
    get:()=>clone(policy),
    set:value=>{policy=save(value);document.querySelectorAll('.portfolio-policy-card').forEach(x=>x.remove());inject();return clone(policy)},
    reset:()=>{policy=save(DEFAULT);document.querySelectorAll('.portfolio-policy-card').forEach(x=>x.remove());inject();return clone(policy)},
  };
})();
