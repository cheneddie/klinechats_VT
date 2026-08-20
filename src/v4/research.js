window.FabioV4=window.FabioV4||{};
(()=>{
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=v=>v==null?'—':`${(Number(v)*100).toFixed(1)}%`;
const num=(v,d=2)=>v==null?'—':Number(v).toFixed(d);
const route=()=>location.hash.replace(/^#\/?/,'').split('/').filter(Boolean)[0]||'dashboard';
const state={years:'2025',busy:false};
function classify(r){
  if(Number(r.universe||0)<50)return['insufficient','樣本不足'];
  if(Number(r.same_seq_parent_rate||0)>=.8&&Math.abs(Number(r.filter_score||0))<.05)return['redundant','高度重複'];
  if(Number(r.filter_score||0)>=.15)return['useful','候選有效 Gate'];
  if(Number(r.filter_score||0)<=-.10)return['harmful','可能誤殺贏家'];
  return['neutral','中性 / 待 OOS'];
}
function panel(){
  const content=$('#content');if(!content)return null;
  let host=$('#v4EdgeAudit');
  if(host)return host;
  host=document.createElement('section');host.id='v4EdgeAudit';host.className='v4-edge-audit';
  content.prepend(host);return host;
}
async function load(){
  const host=panel();if(!host)return;
  host.innerHTML=`<div class="v4-audit-head"><div><span>V4 · REVERSE NODE EDGE AUDIT</span><h2>從終端交易機會逆推：每個 Node 到底保留贏家、排除輸家，還是只是重複？</h2><p>Universe 使用 shadow downstream construction 的未套上游 Gate 終端機會，不直接用 MR_ENTRY / BO_ENTRY=YES 當母體，避免循環論證。</p></div><div class="v4-audit-actions"><label>年份 <input id="v4AuditYears" value="${esc(state.years)}"></label><button id="v4Outcome">① 計算 Outcomes</button><button id="v4Reverse" class="primary">② 逆推 Node Audit</button><button id="v4Refresh">重新整理</button></div></div><div id="v4AuditBody"><div class="v4-audit-empty">尚未讀取 Audit。</div></div>`;
  $('#v4AuditYears').onchange=e=>state.years=e.target.value;
  $('#v4Outcome').onclick=()=>runOutcomes();
  $('#v4Reverse').onclick=()=>runReverse();
  $('#v4Refresh').onclick=()=>refresh();
  await refresh();
}
async function runOutcomes(){
  if(state.busy)return;state.busy=true;
  const body=$('#v4AuditBody');body.innerHTML='<div class="v4-audit-empty">正在用 physical Tick path 計算 MFE / MAE / 1R / 2R / 3R 與多種追蹤止盈…</div>';
  try{
    const q=new URLSearchParams({years:state.years,max_after_days:'1'});
    const r=await FabioV2.store.api('/v4/audit/outcomes?'+q,{method:'POST'});
    body.innerHTML=`<div class="v4-audit-empty">完成 ${Number(r.computed||0).toLocaleString()} 個終端機會 Outcome。現在執行「逆推 Node Audit」。</div>`;
  }catch(e){body.innerHTML='<div class="v4-audit-empty">Outcome 失敗：'+esc(e.message||e)+'</div>'}
  finally{state.busy=false}
}
async function runReverse(){
  if(state.busy)return;state.busy=true;
  const body=$('#v4AuditBody');body.innerHTML='<div class="v4-audit-empty">逆推每個 Gate 對大贏家 / 大輸家的保留與排除效果…</div>';
  try{
    const q=new URLSearchParams({years:state.years});
    await FabioV2.store.api('/v4/audit/reverse?'+q,{method:'POST'});
    await refresh();
  }catch(e){body.innerHTML='<div class="v4-audit-empty">Reverse Audit 失敗：'+esc(e.message||e)+'</div>'}
  finally{state.busy=false}
}
function auditTable(items){
  if(!items.length)return'<div class="v4-audit-empty">尚無 Audit。先計算 Outcomes，再執行 Reverse Audit。</div>';
  return `<div class="v4-table-wrap"><table class="v4-audit-table"><thead><tr>
    <th>Node</th><th>策略</th><th>Universe</th><th>Pass / Fail</th>
    <th>≥2R 贏家保留</th><th>大虧損排除</th><th>Pass 2R</th><th>Fail 2R</th>
    <th>Pass MFE</th><th>Fail MFE</th><th>同 Parent 同點</th><th>Filter Score</th><th>判讀</th>
  </tr></thead><tbody>${items.map(r=>{
    const [cl,txt]=classify(r),bw=Number(r.big_winners||0),bl=Number(r.big_losers||0);
    return `<tr><td><b>${esc(FabioV2.nodeMap?.[r.node_id]?.code||r.node_id)}</b><small>${esc(FabioV2.nodeMap?.[r.node_id]?.short||'')}</small></td>
      <td>${esc(r.strategy)}</td><td>${Number(r.universe||0).toLocaleString()}</td><td>${r.pass_count} / ${r.fail_count}</td>
      <td>${bw?`${r.big_winners_kept}/${bw} (${pct(r.big_winners_kept/bw)})`:'—'}</td>
      <td>${bl?`${r.big_losers_rejected}/${bl} (${pct(r.big_losers_rejected/bl)})`:'—'}</td>
      <td>${pct(r.pass_2r_rate)}</td><td>${pct(r.fail_2r_rate)}</td>
      <td>${num(r.pass_avg_mfe_r)}R</td><td>${num(r.fail_avg_mfe_r)}R</td>
      <td>${pct(r.same_seq_parent_rate)}</td><td>${num(r.filter_score,3)}</td>
      <td><span class="v4-audit-badge ${cl}">${txt}</span></td></tr>`}).join('')}</tbody></table></div>`;
}
function mgmtTable(items){
  if(!items.length)return'<div class="v4-audit-empty">尚無 Trade Management 統計。</div>';
  return `<div class="v4-table-wrap"><table class="v4-audit-table"><thead><tr><th>策略</th><th>管理法</th><th>N</th><th>Avg R</th><th>Median</th><th>Win Rate</th><th>P90</th></tr></thead><tbody>${items.map(x=>`<tr><td>${esc(x.strategy)}</td><td>${esc(x.name)}</td><td>${x.n}</td><td>${num(x.avg_r)}R</td><td>${num(x.median_r)}R</td><td>${pct(x.win_rate)}</td><td>${num(x.p90_r)}R</td></tr>`).join('')}</tbody></table></div>`;
}
function ablationTable(data){
  const blocks=[];
  for(const st of ['MR','BO']){
    const rows=data?.[st]||[];if(!rows.length)continue;
    blocks.push(`<div class="v4-ablation"><h4>${st} Ablation</h4><table class="v4-audit-table"><thead><tr><th>移除 Gate</th><th>N</th><th>2R Rate</th><th>Avg MFE</th><th>Avg MAE</th><th>比完整多出的機會</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(x.removed)}</td><td>${x.n}</td><td>${pct(x.hit_2r_rate)}</td><td>${num(x.avg_mfe_r)}R</td><td>${num(x.avg_mae_r)}R</td><td>${x.added_vs_full}</td></tr>`).join('')}</tbody></table></div>`);
  }
  return blocks.join('')||'<div class="v4-audit-empty">尚無 Ablation 資料。</div>';
}
async function refresh(){
  const body=$('#v4AuditBody');if(!body)return;
  try{
    const [a,m,ab]=await Promise.all([
      FabioV2.store.api('/v4/audit/latest'),
      FabioV2.store.api('/v4/management/summary'),
      FabioV2.store.api('/v4/audit/ablation?'+new URLSearchParams({years:state.years}))
    ]);
    body.innerHTML=`<section><div class="v4-sec-head"><h3>Reverse Node Edge Audit</h3><span>${esc(a.audit_id||'NO AUDIT')}</span></div>${auditTable(a.items||[])}</section>
      <section><div class="v4-sec-head"><h3>Trade Management Lab</h3><span>Fixed target 是 control group；其餘測 trailing / runner</span></div>${mgmtTable(m.items||[])}</section>
      <section><div class="v4-sec-head"><h3>Ablation Test</h3><span>完整 Gate Chain vs 每次拿掉一個 Node</span></div>${ablationTable(ab)}</section>`;
  }catch(e){body.innerHTML='<div class="v4-audit-empty">V4 API 尚未啟動或沒有資料：'+esc(e.message||e)+'</div>'}
}
function ensure(){if(route()!=='research')return;if(!$('#v4EdgeAudit'))load()}
const mo=new MutationObserver(()=>{if(route()==='research'&&!$('#v4EdgeAudit'))setTimeout(ensure,0)});
mo.observe(document.documentElement,{subtree:true,childList:true});
window.addEventListener('hashchange',()=>setTimeout(ensure,40));
setTimeout(ensure,1000);
FabioV4.research={load,refresh,classify};
})();
