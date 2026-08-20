import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const practice=fs.readFileSync('src/v4/practice.js','utf8')
const replay=fs.readFileSync('src/v4/replay.js','utf8')
const chart=fs.readFileSync('src/v4/chart.js','utf8')
const research=fs.readFileSync('src/v4/research.js','utf8')
const index=fs.readFileSync('index.html','utf8')

test('V4 practice uses lazy API node loading and balanced YES/NO pools',()=>{
  assert.match(practice,/loadNodeCases\(nodeId/)
  assert.match(practice,/answer:true/)
  assert.match(practice,/answer:false/)
  assert.match(practice,/practice-v4/)
  assert.match(practice,/HIDE FUTURE/)
})

test('V4 replay exposes trading-day context and selectable timeframes',()=>{
  for(const tf of ['1s','5s','15s','30s','1m','3m','5m','15m','30m'])assert.match(chart,new RegExp(`['"]${tf}['"]`))
  assert.match(replay,/before:1,after:1/)
  assert.match(replay,/Trade Management/)
  assert.match(replay,/physical _seq/)
})

test('V4 research exposes reverse audit and ablation without claiming final OOS validation',()=>{
  assert.match(research,/REVERSE NODE EDGE AUDIT/)
  assert.match(research,/shadow downstream construction/)
  assert.match(research,/Ablation Test/)
  assert.match(research,/待 OOS/)
})

test('V4 modules are wired after V3 dependencies',()=>{
  assert.match(index,/Fabio Decision Gym V4/)
  assert.match(index,/src\/v4\/chart\.js/)
  assert.match(index,/src\/v4\/practice\.js/)
  assert.match(index,/src\/v4\/replay\.js/)
  assert.match(index,/src\/v4\/research\.js/)
})
