window.FabioV4=window.FabioV4||{};
(()=>{
let active=null;
const fmt={seconds:['1s','5s','15s','30s'],minutes:['1m','3m','5m','15m','30m']};
async function api(path){return FabioV2.store.api(path)}
function dispose(){
  if(!active)return;
  try{active.layer?.destroy?.()}catch{}
  try{klinecharts.dispose(active.host)}catch{}
  active=null;
}
function metaTime(c,nodeId){
  const m=c?.nodeMeta?.[nodeId];
  return m?.decision_time||m?.anchor_time||c?.entryTime||c?.entry_time||c?.attemptStartTime||c?.attempt_start_time;
}
async function fetchWindow(c,{nodeId=null,timeframe='1m',before=1,after=1,session='full',hideFuture=false}={}){
  const q=new URLSearchParams({
    timeframe,days_before:String(before),days_after:String(after),session,
    hide_future:String(Boolean(hideFuture))
  });
  if(nodeId)q.set('node_id',nodeId);
  return api('/v4/replay/'+encodeURIComponent(c.id)+'?'+q.toString());
}
async function render(host,c,opts={}){
  if(!host||!c)return null;
  dispose();
  host.innerHTML='<div class="empty-chart">V4 Replay：載入交易日資料…</div>';
  let payload;
  try{payload=await fetchWindow(c,opts)}catch(e){
    host.innerHTML='<div class="empty-chart">V4 Replay 載入失敗：'+String(e.message||e)+'</div>';
    return null;
  }
  if(payload?.case)Object.assign(c,payload.case);
  let bars=payload?.bars||[];
  /* Defensive only. Server already cuts physical rows before aggregation when
     hide_future=true. Never depend on this bar-level filter for causality. */
  if(opts.hideFuture&&payload?.cutoff_time){
    const cut=Date.parse(payload.cutoff_time);
    if(Number.isFinite(cut))bars=bars.filter(b=>Number(b.timestamp)<=cut);
  }
  if(!bars.length){host.innerHTML='<div class="empty-chart">此範圍沒有 Replay bars。</div>';return null}
  host.innerHTML='';
  const chart=klinecharts.init(host,{locale:'zh-TW',timezone:'Asia/Taipei',styles:{
    grid:{horizontal:{color:'#1e2a3b'},vertical:{color:'#172333'}},
    candle:{bar:{upColor:'#27d3a2',downColor:'#ff6378',upBorderColor:'#27d3a2',downBorderColor:'#ff6378',upWickColor:'#27d3a2',downWickColor:'#ff6378'}}
  }});
  chart.setSymbol({ticker:`MTX ${c.contract||''} · ${opts.timeframe||'1m'}`,pricePrecision:0,volumePrecision:0});
  const tf=String(opts.timeframe||'1m');
  chart.setPeriod({span:Number(tf.replace(/\D/g,''))||1,type:tf.endsWith('s')?'second':'minute'});
  chart.setDataLoader({getBars:({callback})=>callback(bars,{forward:false,backward:false})});
  try{chart.createIndicator('VOL',{pane:{height:72}})}catch{}
  let layer=null;
  await new Promise(r=>setTimeout(r,100));
  if(window.FabioV3?.pixi){
    layer=await FabioV3.pixi.mount(host,chart,c,bars,{visualMode:opts.visualMode||'teaching'});
    if(opts.nodeId&&opts.visualMode==='single')layer.focus(opts.nodeId,{scroll:true});
  }
  active={host,chart,layer,c,bars,payload,opts};
  document.dispatchEvent(new CustomEvent('fabio:v4-chart-rendered',{detail:{
    eventId:c.id,nodeId:opts.nodeId,timeframe:tf,hideFuture:Boolean(opts.hideFuture),
    bars:bars.length,dates:payload?.dates||[],sourceRows:payload?.source_rows||0,cutoffTime:payload?.cutoff_time||null
  }}));
  return active;
}
FabioV4.chart={render,fetchWindow,dispose,current:()=>active,timeframes:[...fmt.seconds,...fmt.minutes],metaTime};
})();
