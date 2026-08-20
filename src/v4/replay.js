window.FabioV4=window.FabioV4||{};
(()=>{
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));
const route=()=>{const p=location.hash.replace(/^#\/?/,'').split('/').filter(Boolean);return{page:p[0]||'dashboard',id:p[1]?decodeURIComponent(p[1]):null}};
const state={caseId:null,timeframe:'1m',before:1,after:1,session:'full',mode:'single',nodeId:null,loading:false,renderSig:null};
function savedNode(){try{return sessionStorage.getItem('fabioV3FocusNode')}catch{return null}}
function modeOptions(){return[['single','目前節點'],['teaching','全部決策'],['blind','裸圖']]}
function toolbar(){
  let host=$('#v4ReplayControls');
  if(host)return host;
  const chart=$('#replayChart'); if(!chart)return null;
  host=document.createElement('div');host.id='v4ReplayControls';host.className='v4-replay-controls';
  chart.parentElement.insertBefore(host,chart);
  return host;
}
async function loadCase(id){
  let c=await FabioV2.store.loadCase(id);
  if(!c&&FabioV2.store.state.apiOnline){
    try{c=await FabioV2.store.api('/cases/'+encodeURIComponent(id))}catch{}
  }
  return c;
}
function drawControls(c){
  const host=toolbar();if(!host)return;
  state.nodeId=state.nodeId||savedNode()||Object.keys(c?.nodes||{})[0]||null;
  host.innerHTML=`
    <div class="v4-r-main">
      <b>V4 Causal Replay</b>
      <label>中心節點 <select id="v4ReplayNode">${Object.keys(c?.nodes||{}).map(id=>`<option value="${id}" ${id===state.nodeId?'selected':''}>${esc(FabioV2.nodeMap?.[id]?.code||id)} · ${esc(FabioV2.nodeMap?.[id]?.short||id)}</option>`).join('')}</select></label>
      <label>週期 <select id="v4ReplayTf">${FabioV4.chart.timeframes.map(x=>`<option ${x===state.timeframe?'selected':''}>${x}</option>`).join('')}</select></label>
      <label>前 <select id="v4Before">${[0,1,2,3].map(x=>`<option value="${x}" ${x===state.before?'selected':''}>${x}交易日</option>`).join('')}</select></label>
      <label>後 <select id="v4After">${[0,1,2,3].map(x=>`<option value="${x}" ${x===state.after?'selected':''}>${x}交易日</option>`).join('')}</select></label>
      <label>Session <select id="v4Session"><option value="full" ${state.session==='full'?'selected':''}>Full</option><option value="day" ${state.session==='day'?'selected':''}>日盤</option></select></label>
      <label>標記 <select id="v4Mode">${modeOptions().map(([v,t])=>`<option value="${v}" ${v===state.mode?'selected':''}>${t}</option>`).join('')}</select></label>
      <button id="v4Reload">重新載入</button>
      <button id="v4Mgmt" class="primary">Trade Management</button>
    </div>
    <div class="v4-r-note">預設：定位節點前後各 1 個交易日。畫面週期只影響視覺；交易結果計算永遠使用原始 physical _seq Tick 順序。</div>
    <div id="v4MgmtPanel"></div>`;
  $('#v4ReplayNode').onchange=e=>{state.nodeId=e.target.value;try{sessionStorage.setItem('fabioV3FocusNode',state.nodeId)}catch{};render(c,true)};
  $('#v4ReplayTf').onchange=e=>{state.timeframe=e.target.value;render(c,true)};
  $('#v4Before').onchange=e=>{state.before=+e.target.value;render(c,true)};
  $('#v4After').onchange=e=>{state.after=+e.target.value;render(c,true)};
  $('#v4Session').onchange=e=>{state.session=e.target.value;render(c,true)};
  $('#v4Mode').onchange=e=>{state.mode=e.target.value;render(c,true)};
  $('#v4Reload').onclick=()=>render(c,true);
  $('#v4Mgmt').onclick=()=>showManagement(c);
}
async function render(c,force=false){
  const chart=$('#replayChart');if(!chart||!c)return;
  const sig=[c.id,state.nodeId,state.timeframe,state.before,state.after,state.session,state.mode].join('|');
  if(!force&&state.renderSig===sig)return;
  state.renderSig=sig;
  await FabioV4.chart.render(chart,c,{
    nodeId:state.nodeId,timeframe:state.timeframe,before:state.before,after:state.after,
    session:state.session,hideFuture:false,visualMode:state.mode
  });
  const layer=FabioV4.chart.current()?.layer;
  if(layer&&state.nodeId&&state.mode==='single')layer.focus(state.nodeId,{scroll:true});
}
function mgmtTable(d){
  const m=d?.management||{};
  const rows=Object.entries(m).sort((a,b)=>(b[1]?.r??-999)-(a[1]?.r??-999));
  if(!rows.length)return'<div class="v4-mgmt-empty">尚無管理結果。</div>';
  return `<div class="v4-mgmt-summary">
    <div><span>MFE</span><b>${Number(d.mfe_r||0).toFixed(2)}R</b></div>
    <div><span>MAE</span><b>${Number(d.mae_r||0).toFixed(2)}R</b></div>
    <div><span>2R before stop</span><b>${d.hit_2r?'YES':'NO'}</b></div>
  </div><table class="v4-mgmt-table"><thead><tr><th>管理法</th><th>實現 R</th><th>Exit _seq</th></tr></thead><tbody>${rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td class="${Number(v.r)>=0?'pos':'neg'}">${Number(v.r).toFixed(2)}R</td><td>${v.exit_seq??'—'}</td></tr>`).join('')}</tbody></table>`;
}
async function showManagement(c){
  const p=$('#v4MgmtPanel');if(!p)return;
  p.innerHTML='<div class="v4-mgmt-empty">用 physical Tick path 計算此案例管理策略…</div>';
  try{
    let d;
    try{d=await FabioV2.store.api('/v4/management/'+encodeURIComponent(c.id))}
    catch{
      d=await FabioV2.store.api('/v4/management/simulate/'+encodeURIComponent(c.id),{method:'POST'});
    }
    p.innerHTML=mgmtTable(d);
  }catch(e){
    p.innerHTML='<div class="v4-mgmt-empty">無法計算：'+esc(e.message||e)+'</div>';
  }
}
async function ensure(){
  const r=route();if(r.page!=='replay'||!r.id)return;
  if(state.caseId!==r.id){state.caseId=r.id;state.renderSig=null;state.nodeId=savedNode()}
  const c=await loadCase(r.id);if(!c)return;
  drawControls(c);render(c);
}
const mo=new MutationObserver(()=>{if(route().page==='replay'&&$('#replayChart')&&!$('#v4ReplayControls'))setTimeout(ensure,0)});
mo.observe(document.documentElement,{subtree:true,childList:true});
window.addEventListener('hashchange',()=>setTimeout(ensure,40));
setTimeout(ensure,900);
FabioV4.replay={ensure,render,get state(){return state}};
})();
