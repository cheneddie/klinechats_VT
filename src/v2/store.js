window.FabioV2=window.FabioV2||{};
(()=>{
const KEY='fabioDecisionGymV2';
const defaultSettings={apiBase:'http://127.0.0.1:8765/api',questionCount:20,difficulty:[1,2,3,4,5],yesRatio:0.5,chartSeconds:5,showValue:true,showProfile:true,hints:true,randomize:true,strategyVersion:'MR_BROAD_V3',trainingMode:'practice'};
function loadLocal(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch{return {}}}
const saved=loadLocal();
const state={settings:{...defaultSettings,...saved.settings},history:saved.history||[],spaced:saved.spaced||[],cases:[],datasets:[],nodeStats:{},apiOnline:false,currentCase:null,currentNode:null,sessionAnswers:[]};
function persist(){localStorage.setItem(KEY,JSON.stringify({settings:state.settings,history:state.history.slice(-10000),spaced:state.spaced.slice(-2000)}))}
function pathToNodes(c){const p=c.answerPath||[];const out={};
 if(c.strategy==='MR'){
  out.CTX_VALUE=true;out.AUC_ATTEMPT=p.includes('AUCTION_YES');out.MR_REJECTION=p.includes('REJECTION_YES');out.MR_CLEAR_RECLAIM=p.includes('CLEAR_RECLAIM_YES');out.MR_RECLAIM_LEG=p.includes('LEG_YES');out.MR_LVN=p.includes('LVN_YES');out.MR_PULLBACK=p.includes('PULLBACK_YES');out.MR_ENTRY=p.includes('EXECUTE_MR')||Boolean(c.entryTime);
 } else if(c.strategy==='BO'){
  out.CTX_VALUE=true;out.AUC_ATTEMPT=p.includes('AUCTION_YES');out.MR_REJECTION=p.includes('REJECTION_YES');out.BO_ACCEPTANCE=p.includes('ACCEPTANCE_YES');out.BO_DISPLACEMENT=p.includes('DISPLACEMENT_YES');out.BO_IMPULSE_LEG=p.includes('IMPULSE_LEG_YES');out.BO_LVN=p.includes('LVN_YES');out.BO_PULLBACK=p.includes('PULLBACK_YES');out.BO_RESPONSE=p.includes('RESPONSE_YES');out.BO_ENTRY=p.includes('EXECUTE_BO');
 }
 return out}
function normalizeCase(c,i){const nodes=c.nodes||pathToNodes(c);return {...c,_i:i,nodes,year:Number(String(c.date||'').slice(0,4))||0,difficulty:c.difficulty||Math.min(5,Math.max(1,2+Object.values(nodes).filter(v=>v===false).length)),result:c.result||((c.entryTime||c.entrySeq)?'ENTRY':'WAIT'),regime:c.regime||'unknown'} }
function fallbackCases(){const raw=window.__REPLAY_DATA__?.cases||[];const normalized=raw.map(normalizeCase);if(normalized.length)return normalized;return []}
async function api(path,opts){const base=state.settings.apiBase.replace(/\/$/,'');const r=await fetch(base+path,{signal:AbortSignal.timeout(2500),...opts});if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);return r.json()}
async function boot(){state.cases=fallbackCases();try{const h=await api('/health');state.apiOnline=Boolean(h?.ok);if(state.apiOnline){const [cases,datasets]=await Promise.all([api('/cases?limit=5000'),api('/datasets')]);if(Array.isArray(cases?.items))state.cases=cases.items.map(normalizeCase);state.datasets=datasets?.items||datasets||[]}}catch{state.apiOnline=false}recalc();return state}
function recalc(){const stats={};for(const n of FabioV2.nodes)stats[n.id]={node:n.id,total:0,yes:0,no:0,trained:0,correct:0,ms:0,confidence:0};for(const c of state.cases){for(const [id,v] of Object.entries(c.nodes||{})){if(stats[id]&&typeof v==='boolean'){stats[id].total++;v?stats[id].yes++:stats[id].no++}}}for(const h of state.history){const s=stats[h.nodeId];if(!s)continue;s.trained++;if(h.correct)s.correct++;s.ms+=h.ms||0;s.confidence+=h.confidence||0}for(const s of Object.values(stats)){s.accuracy=s.trained?s.correct/s.trained:null;s.avgMs=s.trained?s.ms/s.trained:null;s.avgConfidence=s.trained?s.confidence/s.trained:null;s.remaining=Math.max(0,s.total-s.trained)}state.nodeStats=stats;return stats}
function casesForNode(nodeId,filters={}){let a=state.cases.filter(c=>typeof c.nodes?.[nodeId]==='boolean');if(filters.answer!==undefined)a=a.filter(c=>c.nodes[nodeId]===filters.answer);if(filters.branch)a=a.filter(c=>c.strategy===filters.branch);if(filters.year)a=a.filter(c=>c.year===Number(filters.year));if(filters.direction)a=a.filter(c=>c.direction===filters.direction);if(filters.difficulty)a=a.filter(c=>c.difficulty===Number(filters.difficulty));if(filters.result)a=a.filter(c=>c.result===filters.result);return a}
function record({caseId,nodeId,answer,correct,ms,confidence,mode='practice'}){const row={id:crypto.randomUUID?.()||`${Date.now()}-${Math.random()}`,at:new Date().toISOString(),caseId,nodeId,answer:Boolean(answer),correct:Boolean(correct),ms:Math.round(ms||0),confidence:Number(confidence||3),mode};state.history.push(row);if(!correct)schedule(row);persist();recalc();return row}
function schedule(row){const due=[10*60e3,24*3600e3,3*24*3600e3,7*24*3600e3,30*24*3600e3];for(let i=0;i<due.length;i++)state.spaced.push({caseId:row.caseId,nodeId:row.nodeId,level:i+1,dueAt:new Date(Date.now()+due[i]).toISOString(),done:false})}
function dueReviews(){const now=Date.now();return state.spaced.filter(x=>!x.done&&Date.parse(x.dueAt)<=now)}
function markReviewDone(caseId,nodeId){const x=state.spaced.find(x=>!x.done&&x.caseId===caseId&&x.nodeId===nodeId);if(x)x.done=true;persist()}
function weakestNodes(limit=5){return Object.values(state.nodeStats).filter(x=>x.trained>=1).sort((a,b)=>(a.accuracy??1)-(b.accuracy??1)||b.trained-a.trained).slice(0,limit)}
function highConfidenceMistakes(){return state.history.filter(h=>!h.correct&&h.confidence>=4).slice(-100).reverse()}
function exportHistory(){const blob=new Blob([JSON.stringify({version:2,exportedAt:new Date().toISOString(),settings:state.settings,history:state.history,spaced:state.spaced},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`fabio-decision-gym-${new Date().toISOString().slice(0,10)}.json`;a.click();URL.revokeObjectURL(a.href)}
function updateSettings(patch){Object.assign(state.settings,patch);persist()}
FabioV2.store={state,boot,api,recalc,casesForNode,record,dueReviews,markReviewDone,weakestNodes,highConfidenceMistakes,exportHistory,updateSettings,persist};
})();