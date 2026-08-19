import test from 'node:test'
import assert from 'node:assert/strict'
await import('../src/trainer-core.js')
const core=globalThis.TrainerCore

test('summarize computes accuracy, speed and weakest node',()=>{
  const h=[
    {strategy:'MR',tag:'AUCTION',ok:true,ms:1000,confidence:4},
    {strategy:'MR',tag:'LOCATION',ok:false,ms:2000,confidence:5},
    {strategy:'BO',tag:'AUCTION',ok:true,ms:3000,confidence:3}
  ]
  const s=core.summarize(h)
  assert.equal(s.n,3)
  assert.equal(s.correct,2)
  assert.ok(Math.abs(s.accuracy-2/3)<1e-12)
  assert.equal(s.avgMs,2000)
  assert.equal(s.weakest.node,'LOCATION')
  assert.equal(s.byStrategy.MR.n,2)
})

test('confidence calibration preserves empty buckets',()=>{
  const b=core.confidenceCalibration([{confidence:5,ok:true},{confidence:5,ok:false},{confidence:2,ok:true}])
  assert.equal(b.length,5)
  assert.equal(b.find(x=>x.level===5).accuracy,0.5)
  assert.equal(b.find(x=>x.level===1).n,0)
})

test('randomCase respects strategy and exclusion',()=>{
  const cases=[{id:'a',strategy:'MR'},{id:'b',strategy:'MR'},{id:'c',strategy:'BO'}]
  for(let i=0;i<20;i++) assert.equal(core.randomCase(cases,{strategy:'BO'}).id,'c')
  assert.notEqual(core.randomCase(cases,{strategy:'MR',excludeId:'a'}).id,'a')
})
