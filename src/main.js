const $=s=>document.querySelector(s)
const state={data:null,case:null,bars:[],visible:35,playing:false,timer:null,q:0,score:0,answered:0,chart:null}
const questions={
 MR:[
  ['AUCTION','價格是否真正離開 Previous Value？','不要把 VAH/VAL 附近 1～2 點抖動當成 Auction Attempt。',true,'市場已經離開 Value，形成可追蹤的拍賣嘗試。'],
  ['REJECTION','新價格是否被快速拒絕並 Clear Reclaim？','被拒絕才進入「回家」的均值回歸路徑。',true,'這是一個 Failed Auction：外部價格沒有被接受。'],
  ['CAUSAL LEG','是否已形成可確認的 Reclaim Leg？','不能事後畫腿；當下必須已有足夠位移與轉折確認。',true,'Reclaim Leg 已成立，現在才有資格對這段畫 Volume Profile。'],
  ['LOCATION','Reclaim Leg 上是否存在合法 LVN？','LVN 是位置，不是單獨的進場訊號。',true,'找到低成交谷底，可等待第一次合法 Pullback。'],
  ['ENTRY','現在是否已到第一個合法 LVN Pullback？','錯過就不要追；好 Setup 不代表任何價格都值得進。',true,'符合 Entry 條件；下一階段才揭曉 Stop / Target / 結果。']
 ],
 BO:[
  ['AUCTION','價格是否真正離開 Previous Value？','先確認是 Auction Attempt，不猜突破真假。',true,'市場已經離開舊 Value。'],
  ['REJECTION','市場是否已經快速 Clear Reclaim 回舊 Value？','如果答案是 YES，就應該轉去評估 Mean Reversion。',false,'沒有快速 Reclaim，不能硬做均值回歸。'],
  ['ACCEPTANCE','價格是否持續留在 Value 外並形成 Acceptance？','看停留、位移與外部成交，不用一根 K 棒定生死。',true,'新價格正在被接受，進入突破回測候選。'],
  ['DISPLACEMENT','是否有足夠的單方向 Displacement？','弱突破不追；要看到真正重新定價。',true,'Displacement 成立。'],
  ['IMPULSE LEG','Impulse Leg 是否已完整到可以畫 Profile？','尚未形成完整腿就應 WAIT。',false,'目前答案是 WAIT：讓市場先把腿走完整。']
 ]
}

async function boot(){
 if(window.__REPLAY_DATA__){state.data=window.__REPLAY_DATA__}else{const res=await fetch('./public/data/demo_case.json');state.data=await res.json()}
 const sel=$('#caseSelect'); const useful=state.data.cases.filter(c=>c.strategy==='MR').concat(state.data.cases.filter(c=>c.strategy==='BO').slice(0,20))
 useful.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=`${c.date} · ${c.strategy==='MR'?'均值回歸':'突破回測'} · ${c.direction==='long'?'多':'空'}`;sel.appendChild(o)})
 const preferred=useful.find(c=>c.id.includes('2026-08-11-MR-10'))||useful[0];sel.value=preferred.id
 sel.addEventListener('change',()=>loadCase(sel.value));
 $('#yesBtn').addEventListener('click',()=>answer(true));$('#noBtn').addEventListener('click',()=>answer(false));
 $('#playBtn').addEventListener('click',togglePlay);$('#stepBtn').addEventListener('click',()=>step(1));$('#backBtn').addEventListener('click',()=>step(-1));
 $('#timeline').addEventListener('input',e=>{state.visible=+e.target.value;renderChart()});
 $('#speedSelect').addEventListener('change',()=>{if(state.playing){stopPlay();startPlay()}})
 await loadCase(preferred.id)
}

async function loadCase(id){
 state.case=state.data.cases.find(c=>c.id===id);const sess=state.data.sessions[state.case.date];state.bars=sess.bars
 const eventTs=Date.parse(state.case.attemptStartTime);let eventIndex=state.bars.findIndex(b=>b.timestamp>=eventTs);if(eventIndex<0)eventIndex=30
 state.visible=Math.max(25,Math.min(state.bars.length,eventIndex+8));$('#timeline').min=15;$('#timeline').max=state.bars.length;$('#timeline').value=state.visible
 state.q=0;state.score=0;state.answered=0;stopPlay();updateMeta();updateQuestion();renderChart()
}
function updateMeta(){const c=state.case,p=c.priorProfile;$('#sessionLabel').textContent=c.date;$('#vahText').textContent=p.vah.toFixed(0);$('#pocText').textContent=p.poc.toFixed(0);$('#valText').textContent=p.val.toFixed(0);$('#eventTime').textContent=timeOnly(c.attemptStartTime);$('#extremeText').textContent=`${c.extremePrice?.toFixed?.(0)||c.extremePrice} @ ${timeOnly(c.extremeTime)}`;$('#lvnText').textContent=c.lvn?c.lvn.toFixed(0):'尚未形成';$('#entryText').textContent='尚未揭曉';$('#strategyBadge').textContent=c.strategy==='MR'?'MR 候選':'BO 候選';$('#scoreText').textContent='0'}
function qlist(){return questions[state.case.strategy]||questions.BO}
function updateQuestion(){const q=qlist()[state.q]||qlist().at(-1);$('#questionTag').textContent=`Q${state.q+1} · ${q[0]}`;$('#questionText').textContent=q[1];$('#questionHint').textContent=q[2];$('#feedback').className='feedback muted';$('#feedback').textContent='選擇答案後才顯示解析。';document.querySelectorAll('.route-node').forEach((n,i)=>n.classList.toggle('active',i===Math.min(state.q,4)))}
function answer(v){const q=qlist()[state.q];if(!q)return;state.answered++;const ok=v===q[3];if(ok)state.score++;$('#scoreText').textContent=Math.round(state.score/state.answered*100);const f=$('#feedback');f.className=`feedback ${ok?'good':'bad'}`;f.textContent=(ok?'✓ 判斷正確：':'✕ 再想一下：')+q[4];setTimeout(()=>{if(state.q<qlist().length-1){state.q++;updateQuestion();revealToQuestion()}else revealOutcome()},650)}
function revealToQuestion(){const c=state.case;const times=[c.attemptStartTime,c.clearReclaimTime||c.extremeTime,c.turnConfirmTime||c.extremeTime,c.turnConfirmTime||c.extremeTime,c.entryTime||c.extremeTime];const t=Date.parse(times[Math.min(state.q,times.length-1)]||c.extremeTime);const idx=state.bars.findIndex(b=>b.timestamp>=t);if(idx>0){state.visible=Math.min(state.bars.length,idx+5);$('#timeline').value=state.visible;renderChart()}}
function revealOutcome(){const c=state.case;if(c.entryTime){$('#entryText').textContent=`${c.entryPrice.toFixed(0)} @ ${timeOnly(c.entryTime)}`;$('#strategyBadge').textContent=c.direction==='long'?'EXECUTE LONG':'EXECUTE SHORT'}else{$('#entryText').textContent='WAIT / NO TRADE';$('#strategyBadge').textContent=c.strategy==='MR'?'MR · WAIT':'BO · WAIT'}state.visible=Math.min(state.bars.length,state.visible+15);$('#timeline').value=state.visible;renderChart(true)}
function step(n){state.visible=Math.max(15,Math.min(state.bars.length,state.visible+n));$('#timeline').value=state.visible;renderChart()}
function togglePlay(){state.playing?stopPlay():startPlay()}function startPlay(){state.playing=true;$('#playBtn').textContent='Ⅱ';const ms=+$('#speedSelect').value;state.timer=setInterval(()=>{if(state.visible>=state.bars.length)return stopPlay();step(1)},ms)}function stopPlay(){state.playing=false;$('#playBtn').textContent='▶';if(state.timer)clearInterval(state.timer);state.timer=null}
function timeOnly(s){if(!s)return'—';return s.slice(11,19)}

function renderChart(showTrade=false){
 const bars=state.bars.slice(0,state.visible);if(!bars.length)return;const last=bars.at(-1);$('#replayClock').textContent=new Date(last.timestamp).toLocaleString('zh-TW',{hour12:false});$('#barStats').textContent=`O ${last.open.toFixed(0)}  H ${last.high.toFixed(0)}  L ${last.low.toFixed(0)}  C ${last.close.toFixed(0)}`
 if(state.chart){try{klinecharts.dispose('chart')}catch(e){}};
 const chart=klinecharts.init('chart',{locale:'zh-TW',timezone:'Asia/Taipei',styles:{grid:{horizontal:{color:'#1b2b40'},vertical:{color:'#152438'}},candle:{bar:{upColor:'#22c89a',downColor:'#f05469',upBorderColor:'#22c89a',downBorderColor:'#f05469',upWickColor:'#22c89a',downWickColor:'#f05469'}}}});state.chart=chart
 chart.setSymbol({ticker:'MTX202608',pricePrecision:0,volumePrecision:0});chart.setPeriod({span:1,type:'minute'});chart.setDataLoader({getBars:({callback})=>callback(bars)});try{chart.createIndicator('VOL',{pane:{height:90}})}catch(e){}
 setTimeout(()=>{drawLevels(chart,bars,showTrade)},60)
}
function drawLevels(chart,bars,showTrade){const c=state.case,p=c.priorProfile;const t0=bars[0].timestamp,t1=bars.at(-1).timestamp;const mk=(value,color,label)=>{try{chart.createOverlay({name:'horizontalSegment',lock:true,points:[{timestamp:t0,value},{timestamp:t1,value}],styles:{line:{color,size:1,style:'dashed'},text:{color}}})}catch(e){}};mk(p.vah,'#ff667d','VAH');mk(p.poc,'#f2bb57','POC');mk(p.val,'#2bd7a5','VAL');if(c.lvn)mk(c.lvn,'#9b7cff','LVN');if(showTrade&&c.entryTime){mk(c.stop,'#ff5d74','STOP');mk(c.target,'#26d7a2','TARGET')}}
boot().catch(err=>{console.error(err);$('#engineBadge').textContent='啟動失敗';$('#engineBadge').className='badge'})
