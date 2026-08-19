import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function loadWindowScript(path){
  const context={window:{}}
  vm.createContext(context)
  vm.runInContext(fs.readFileSync(path,'utf8'),context)
  return context.window
}

test('demo fixture records the source-order preservation contract',()=>{
  const w=loadWindowScript('public/data/demo_case.js')
  const d=w.__REPLAY_DATA__
  assert.equal(d.meta.sourceOrderPreserved,true)
  assert.equal(d.meta.rows,2115188)
  assert.equal(d.meta.product,'MTX')
  assert.equal(d.meta.expiry,'202608')
  assert.match(d.meta.timestampResolution,/physical row order preserved/)
})

test('1-second replay bars keep increasing physical sequence ranges',()=>{
  const w=loadWindowScript('public/data/phase2_second_bars.js')
  const rows=w.__SECOND_BARS__.rows
  assert.ok(rows.length>100)
  for(let i=0;i<rows.length;i++){
    assert.ok(rows[i][6]<=rows[i][7],`row ${i}: firstSeq <= lastSeq`)
    if(i>0){
      assert.ok(rows[i][0]>=rows[i-1][0],`row ${i}: timestamp not reversed`)
      assert.ok(rows[i][6]>rows[i-1][7],`row ${i}: physical seq strictly advances`)
    }
  }
})

test('KLineChart is pinned to the requested V10 release',()=>{
  const pkg=JSON.parse(fs.readFileSync('package.json','utf8'))
  assert.equal(pkg.dependencies.klinecharts,'10.0.2')
  assert.ok(fs.existsSync('public/vendor/klinecharts-10.0.2.min.js'))
})
