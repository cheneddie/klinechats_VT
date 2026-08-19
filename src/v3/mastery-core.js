window.FabioMasteryCore=(()=>{
  const clamp=(v,lo=0,hi=1)=>Math.max(lo,Math.min(hi,Number(v)||0));
  const safeDiv=(a,b,fallback=0)=>b?Number(a||0)/Number(b):fallback;
  const taipeiDate=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'});
  const dayKey=value=>{const d=value&&typeof value.getTime==='function'?new Date(value.getTime()):new Date(value);if(Number.isNaN(d.getTime()))return'';const p=Object.fromEntries(taipeiDate.formatToParts(d).filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));return`${p.year}-${p.month}-${p.day}`};
  function nodeHistory(history,nodeId){return (history||[]).filter(x=>x.nodeId===nodeId)}
  function recentAccuracy(history,nodeId,limit=20){const rows=nodeHistory(history,nodeId).slice(-limit);return rows.length?safeDiv(rows.filter(x=>x.correct).length,rows.length):null}
  function correctStreak(history,nodeId){const rows=nodeHistory(history,nodeId);let n=0;for(let i=rows.length-1;i>=0;i--){if(!rows[i].correct)break;n++}return n}
  function wrongSignals(history,nodeId,limit=20){const rows=nodeHistory(history,nodeId).slice(-limit);return{recentWrong:rows.filter(x=>!x.correct).length,highConfidenceWrong:rows.filter(x=>!x.correct&&Number(x.confidence)>=4).length}}
  function sampleBalance(stat){const yes=Number(stat?.yes||0),no=Number(stat?.no||0);if(!yes&&!no)return 0;if(!yes||!no)return 0;return Math.min(yes,no)/Math.max(yes,no)}
  function masteryForNode(stat,history=[],dueReviews=[]){
    const nodeId=stat?.node||stat?.id;
    const trained=Number(stat?.trained||0),acc=stat?.accuracy==null?null:clamp(stat.accuracy);
    const recent=recentAccuracy(history,nodeId,20);
    const exposure=clamp(Math.log1p(trained)/Math.log1p(40));
    const balance=sampleBalance(stat);
    const baseAcc=acc==null?0.5:acc,baseRecent=recent==null?baseAcc:recent;
    const evidence=trained?clamp(0.55*baseAcc+0.25*baseRecent+0.15*exposure+0.05*balance):0;
    const score=Math.round(evidence*100);
    const due=(dueReviews||[]).filter(x=>x.nodeId===nodeId&&!x.done).length;
    const signals=wrongSignals(history,nodeId,20);
    let priority=100-score+Math.min(24,due*6)+Math.min(18,signals.recentWrong*3)+Math.min(20,signals.highConfidenceWrong*5);
    if(!trained&&Number(stat?.total||0)>0)priority=82;
    if(!Number(stat?.total||0)&&!trained)priority=0;
    return{nodeId,score,priority:Math.round(priority),trained,accuracy:acc,recentAccuracy:recent,streak:correctStreak(history,nodeId),balance,due,recentWrong:signals.recentWrong,highConfidenceWrong:signals.highConfidenceWrong,total:Number(stat?.total||0),yes:Number(stat?.yes||0),no:Number(stat?.no||0)}
  }
  function buildPlan({nodes=[],nodeStats={},history=[],dueReviews=[],target=20,now=new Date()}={}){
    const rows=nodes.map(n=>({...masteryForNode(nodeStats[n.id]||{node:n.id},history,dueReviews),node:n})).filter(x=>x.total||x.trained).sort((a,b)=>b.priority-a.priority||a.score-b.score||String(a.node?.code||a.nodeId).localeCompare(String(b.node?.code||b.nodeId)));
    const selected=rows.slice(0,3),weights=[0.5,0.3,0.2],goal=Math.max(1,Number(target)||20);
    let used=0;const sessions=selected.map((x,i)=>{let questions=i===selected.length-1?goal-used:Math.max(1,Math.round(goal*weights[i]));used+=questions;return{...x,questions}});
    const trainedRows=rows.filter(x=>x.trained>0);const overall=trainedRows.length?Math.round(trainedRows.reduce((s,x)=>s+x.score,0)/trainedRows.length):0;
    const today=dayKey(now);const todayAttempts=(history||[]).filter(x=>dayKey(x.at)===today).length;
    const wrongQueue=[];const seen=new Set();for(let i=(history||[]).length-1;i>=0;i--){const h=history[i];if(h.correct)continue;const key=`${h.caseId}|${h.nodeId}`;if(seen.has(key))continue;seen.add(key);wrongQueue.push(h);if(wrongQueue.length>=20)break}
    return{overall,todayAttempts,target:goal,todayProgress:clamp(todayAttempts/goal),rows,sessions,wrongQueue,dueCount:(dueReviews||[]).filter(x=>!x.done).length,generatedAt:new Date(now).toISOString()}
  }
  return{dayKey,recentAccuracy,correctStreak,sampleBalance,masteryForNode,buildPlan};
})();
