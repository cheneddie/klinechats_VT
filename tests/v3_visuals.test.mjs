import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function load(file,ctx){vm.runInContext(fs.readFileSync(file,'utf8'),ctx,{filename:file})}
function context(){
  const window={FabioV2:{},FabioV3:{}}
  const ctx=vm.createContext({window,FabioV2:window.FabioV2,FabioV3:window.FabioV3,console,Date,Number,Math,Object,String,Boolean,Array,JSON})
  return ctx
}

test('every registered binary node has a V3 visual specification',()=>{
  const ctx=context()
  load('src/v2/registry.js',ctx)
  load('src/v3/visual-registry.js',ctx)
  const ids=ctx.window.FabioV2.nodes.map(x=>x.id)
  const visual=ctx.window.FabioV3.visualRegistry.nodes
  assert.equal(ids.length,18)
  for(const id of ids){
    assert.ok(visual[id],`missing visual spec: ${id}`)
    assert.ok(visual[id].family)
    assert.ok(visual[id].label)
  }
})

test('visual resolver emits semantic geometry for representative nodes',()=>{
  const ctx=context()
  load('src/v2/registry.js',ctx)
  load('src/v3/visual-registry.js',ctx)
  load('src/v3/node-visuals.js',ctx)
  const t=Date.parse('2025-01-03T09:00:00+08:00')
  const bars=Array.from({length:30},(_,i)=>({timestamp:t+i*1000,open:100+i*.1,high:102+i*.1,low:99+i*.1,close:101+i*.1,volume:1,firstSeq:i*2,lastSeq:i*2+1}))
  const c={
    id:'demo',direction:'short',attemptStartTime:new Date(t+3000).toISOString(),extremeTime:new Date(t+9000).toISOString(),extremePrice:112,
    clearReclaimTime:new Date(t+14000).toISOString(),clearReclaimPrice:104,turnConfirmTime:new Date(t+19000).toISOString(),lvn:105,entryTime:new Date(t+24000).toISOString(),entryPrice:105,stop:111,target:100.5,
    priorProfile:{vah:108,val:98,poc:103,width:10},features:{auction_side:'up',excursion_points:4,excursion_threshold:2},
    nodes:{CTX_VALUE:true,AUC_ATTEMPT:true,AUC_EXTREME:true,MR_REJECTION:true,MR_CLEAR_RECLAIM:true,MR_RECLAIM_LEG:true,MR_LVN:true,MR_PULLBACK:true,MR_ENTRY:true,WAIT_AMBIGUOUS:false,NO_TRADE:false},
    nodeMeta:{AUC_ATTEMPT:{decision_time:new Date(t+3000).toISOString(),decision_seq:6},AUC_EXTREME:{decision_time:new Date(t+9000).toISOString(),decision_seq:18},MR_CLEAR_RECLAIM:{decision_time:new Date(t+14000).toISOString(),decision_seq:28}}
  }
  const out=ctx.window.FabioV3.nodeVisuals.all(c,bars)
  assert.equal(out.length,Object.keys(c.nodes).length)
  assert.equal(out.find(x=>x.nodeId==='CTX_VALUE').family,'context_band')
  assert.equal(out.find(x=>x.nodeId==='AUC_EXTREME').anchor.price,112)
  assert.equal(out.find(x=>x.nodeId==='MR_LVN').range.low,104)
  assert.equal(out.find(x=>x.nodeId==='MR_ENTRY').trade.stop,111)
  assert.ok(out.every(x=>x.style&&x.family))
})

test('PixiJS is pinned to V8 production version',()=>{
  const p=JSON.parse(fs.readFileSync('package.json','utf8'))
  assert.equal(p.dependencies['pixi.js'],'8.19.0')
  assert.match(fs.readFileSync('index.html','utf8'),/pixi-8\.19\.0\.min\.js/)
})
