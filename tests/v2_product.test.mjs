import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html=fs.readFileSync('index.html','utf8');
const app=fs.readFileSync('src/v2/app.js','utf8');
const engine=fs.readFileSync('server/engine.py','utf8');
const pattern=fs.readFileSync('src/v2/pattern-lab.js','utf8');

test('main entry loads KLineChart 10.0.2 and V2 modules',()=>{
  assert.match(html,/klinecharts-10\.0\.2\.min\.js/);
  for(const f of ['registry.js','store.js','chart.js','app.js','lazy.js','safety.js','pattern-lab.js'])
    assert.match(html,new RegExp(f.replace('.','\\.')))
});

test('V2 exposes required training pages',()=>{
  for(const p of ['dashboard','tree','nodes','practice','replay','exam','review','cases','research','settings','data'])
    assert.match(app,new RegExp(`['\"]${p}['\"]`))
});

test('Pattern Lab supports high-volume filters, sizes and compare',()=>{
  assert.match(pattern,/data-filter/);
  assert.match(pattern,/data-limit/);
  assert.match(pattern,/data-drill/);
  assert.match(pattern,/patternCompareModal/);
  for(const n of ['24','48','96','20題','50題','100題']) assert.match(pattern,new RegExp(n));
});

test('engine preserves raw physical tick order',()=>{
  assert.match(engine,/_seq/);
  assert.doesNotMatch(engine,/sort_values\s*\(/);
  assert.match(engine,/OUTRIGHT_RE/);
  assert.match(engine,/choose_contracts/);
  assert.match(engine,/groupby\([^\n]*sort=False/)
});

test('engine stores node instances for fast node queries',()=>{
  assert.match(engine,/CREATE TABLE IF NOT EXISTS node_instances/);
  assert.match(engine,/CREATE INDEX IF NOT EXISTS ix_node/)
});

test('MR and BO directions are intentionally opposite after the same auction',()=>{
  assert.match(engine,/mr_direction\s*=\s*"short" if up else "long"/);
  assert.match(engine,/bo_direction\s*=\s*"long" if up else "short"/)
});
