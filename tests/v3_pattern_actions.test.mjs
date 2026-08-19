import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

test('V3.2 Pattern action adapter guarantees YES/NO and random Replay controls',()=>{
  const src=fs.readFileSync('src/v3/pattern-actions.js','utf8')
  assert.match(src,/data-v32-yn/)
  assert.match(src,/data-v32-random/)
  assert.match(src,/FabioV3\.drill\?\.compareYesNo/)
  assert.match(src,/FabioV3\.drill\?\.setFocusNode/)
  assert.match(src,/MutationObserver/)
})

test('main entry loads Pattern action adapter after V3.2 drill',()=>{
  const html=fs.readFileSync('index.html','utf8')
  assert.match(html,/src\/v3\/pattern-actions\.js/)
  assert.ok(html.indexOf('src/v3/drill.js')<html.indexOf('src/v3/pattern-actions.js'))
})
