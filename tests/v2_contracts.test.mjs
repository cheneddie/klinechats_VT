import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const contracts=fs.readFileSync('server/contracts.py','utf8');
const api=fs.readFileSync('server/fabio_api.py','utf8');
test('strict/front month uses calendar selector, not volume rank',()=>{assert.match(contracts,/causal_front_month/);assert.match(contracts,/third_wednesday/);assert.match(contracts,/if mode=='dominant_volume'/);assert.match(contracts,/causal=True/)});
test('dominant volume is explicitly marked non-causal',()=>{assert.match(contracts,/causal=False/);assert.match(contracts,/whole-day volume/)});
test('local API imports causal engine facade',()=>{assert.match(api,/from \.causal_engine import/)});
