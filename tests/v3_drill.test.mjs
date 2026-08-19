import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const drill=fs.readFileSync('src/v3/drill.js','utf8')
const visuals=fs.readFileSync('src/v3/node-visuals.js','utf8')
const chart=fs.readFileSync('src/v2/chart.js','utf8')
const index=fs.readFileSync('index.html','utf8')

test('V3.2 exposes same-node next/previous/random and YES/NO filters',()=>{
  assert.match(drill,/data-nav="-1"/)
  assert.match(drill,/data-nav="1"/)
  assert.match(drill,/data-nav="random"/)
  assert.match(drill,/data-nfilter="yes"/)
  assert.match(drill,/data-nfilter="no"/)
  assert.match(drill,/loadNodeCases/)
})

test('V3.2 visual compare mounts two real KLine/Pixi panes',()=>{
  assert.match(drill,/v32ChartA/)
  assert.match(drill,/v32ChartB/)
  assert.match(drill,/DecisionPixiLayer/)
  assert.match(drill,/YES vs NO/)
})

test('Practice visual contract is event-driven: blind before answer, focused single node after reveal',()=>{
  assert.match(drill,/function practiceAnswered\(\)/)
  assert.match(drill,/classList\.contains\('correct'\)/)
  assert.match(drill,/classList\.contains\('wrong'\)/)
  assert.match(drill,/function applyPracticeLayer\(layer\)/)
  assert.match(drill,/layer\.setMode\('single'\)/)
  assert.match(drill,/layer\.focus\(r\.id/)
  assert.match(drill,/layer\.setMode\('blind'\)/)
  assert.match(drill,/fabio:pixi-mounted/)
  assert.match(chart,/fabio:pixi-mounted/)
  assert.match(drill,/裸圖判斷中/)
  assert.match(drill,/已揭露 Decision Visual/)
})

test('Reason layer shows actual-vs-threshold evidence and legacy auction-side inference',()=>{
  assert.match(visuals,/實際 Excursion/)
  assert.match(visuals,/深度：實際/)
  assert.match(visuals,/Value 外停留/)
  assert.match(visuals,/physical _seq/)
  assert.match(visuals,/function auctionSide\(c\)/)
})

test('main entry loads drill CSS and JS after visual foundation',()=>{
  assert.match(index,/src\/v3\/drill\.css/)
  assert.match(index,/src\/v3\/drill\.js/)
  assert.ok(index.indexOf('src/v3/visual-ui.js')<index.indexOf('src/v3/drill.js'))
})
