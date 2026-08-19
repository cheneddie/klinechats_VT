import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const contracts=fs.readFileSync('server/contracts.py','utf8');
const api=fs.readFileSync('server/fabio_api.py','utf8');
const scanner=fs.readFileSync('server/scanner.py','utf8');

test('strict/front month exposes calendar selector, not a volume-rank alias',()=>{
  assert.match(contracts,/causal_front_month/);
  assert.match(contracts,/third_wednesday/);
  assert.match(contracts,/mode\s*==\s*['"]dominant_volume['"]/);
  assert.match(contracts,/causal\s*=\s*True/);
  assert.match(contracts,/calendar modes/);
});

test('dominant volume is explicitly marked non-causal',()=>{
  assert.match(contracts,/causal\s*=\s*False/);
  assert.match(contracts,/completed trading day/);
});

test('production imports causal engine facade',()=>{
  assert.match(api,/from \.causal_engine import/);
  assert.match(scanner,/from \.causal_engine import/);
});
