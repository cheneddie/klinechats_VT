import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function core(){
  const context={window:{}}
  context.window=context
  vm.createContext(context)
  vm.runInContext(fs.readFileSync('src/v3/mastery-core.js','utf8'),context,{filename:'src/v3/mastery-core.js'})
  return context.FabioMasteryCore
}

test('V3.3 mastery prioritizes weak, recent-error and due nodes deterministically',()=>{
  const m=core()
  const nodes=[{id:'A',code:'A'},{id:'B',code:'B'},{id:'C',code:'C'}]
  const nodeStats={
    A:{node:'A',total:100,yes:50,no:50,trained:20,correct:19,accuracy:.95},
    B:{node:'B',total:100,yes:50,no:50,trained:20,correct:12,accuracy:.60},
    C:{node:'C',total:100,yes:90,no:10,trained:0,correct:0,accuracy:null},
  }
  const history=[]
  for(let i=0;i<20;i++)history.push({nodeId:'A',correct:i!==0,confidence:3,caseId:`a${i}`,at:'2026-08-20T00:00:00+08:00'})
  for(let i=0;i<20;i++)history.push({nodeId:'B',correct:i%2===0,confidence:i%2?5:3,caseId:`b${i}`,at:'2026-08-20T00:00:00+08:00'})
  const dueReviews=[{nodeId:'B',done:false},{nodeId:'B',done:false}]
  const p1=m.buildPlan({nodes,nodeStats,history,dueReviews,target:20,now:new Date('2026-08-20T12:00:00+08:00')})
  const p2=m.buildPlan({nodes,nodeStats,history,dueReviews,target:20,now:new Date('2026-08-20T12:00:00+08:00')})
  assert.equal(p1.sessions[0].nodeId,'B')
  assert.deepEqual(p1.sessions.map(x=>x.nodeId),p2.sessions.map(x=>x.nodeId))
  assert.equal(p1.sessions.reduce((s,x)=>s+x.questions,0),20)
  assert.ok(p1.rows.find(x=>x.nodeId==='A').score>p1.rows.find(x=>x.nodeId==='B').score)
  assert.ok(p1.rows.find(x=>x.nodeId==='B').highConfidenceWrong>0)
  assert.equal(p1.dueCount,2)
})

test('V3.3 mastery exposes streak, YES/NO balance and unique wrong queue',()=>{
  const m=core()
  const h=[
    {nodeId:'A',correct:false,caseId:'same',confidence:5,at:'2026-08-20T01:00:00+08:00'},
    {nodeId:'A',correct:false,caseId:'same',confidence:4,at:'2026-08-20T02:00:00+08:00'},
    {nodeId:'A',correct:true,caseId:'x',confidence:3,at:'2026-08-20T03:00:00+08:00'},
    {nodeId:'A',correct:true,caseId:'y',confidence:3,at:'2026-08-20T04:00:00+08:00'},
  ]
  const row=m.masteryForNode({node:'A',total:10,yes:5,no:5,trained:4,accuracy:.5},h,[])
  assert.equal(row.streak,2)
  assert.equal(row.balance,1)
  const p=m.buildPlan({nodes:[{id:'A',code:'A'}],nodeStats:{A:{node:'A',total:10,yes:5,no:5,trained:4,accuracy:.5}},history:h,target:10,now:new Date('2026-08-20T12:00:00+08:00')})
  assert.equal(p.wrongQueue.length,1)
  assert.equal(p.todayAttempts,4)
})

test('main entry loads V3.3 mastery CSS and JS after V3.2 drill',()=>{
  const index=fs.readFileSync('index.html','utf8')
  assert.match(index,/src\/v3\/mastery\.css/)
  assert.match(index,/src\/v3\/mastery-core\.js/)
  assert.match(index,/src\/v3\/mastery\.js/)
  assert.ok(index.indexOf('src/v3/drill.js')<index.indexOf('src/v3/mastery.js'))
})
