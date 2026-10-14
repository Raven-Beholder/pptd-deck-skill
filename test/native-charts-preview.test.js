import assert from 'node:assert/strict';
import test from 'node:test';
import { lineSegments, seriesValues, valueRange } from '../skills/pptd-deck-skill/scripts/local-export/native_editor/charts.mjs';

test('line blank behavior preserves source indices for gap, zero and connect', () => {
  const values = [10, null, 30, 20];
  assert.deepEqual(lineSegments(values, 'gap'), [[[0,10]], [[2,30], [3,20]]]);
  assert.deepEqual(lineSegments(values, 'zero'), [[[0,10], [1,0], [2,30], [3,20]]]);
  assert.deepEqual(lineSegments(values, 'connect'), [[[0,10], [2,30], [3,20]]]);
});
test('percent stacks and positive/negative stack domains use totals', () => {
  const chart = { data: {rows: [[],[]]}, xAxis: {}, yAxis: {}, series: [
    {type:'bar', stack:'percent', values:[10,0]}, {type:'bar', stack:'percent', values:[30,null]}] };
  assert.deepEqual(seriesValues(chart), [[.25,0],[.75,null]]);
  assert.deepEqual(valueRange(chart), [0,1]);
  chart.series = [{type:'bar', stack:'value', values:[10,-20]}, {type:'bar', stack:'value', values:[30,-5]}];
  assert.deepEqual(valueRange(chart), [-25,40]);
});
test('horizontal numeric axes honor explicit bounds', () => {
  const chart = { horizontal: true, data: {rows:[[]]}, xAxis:{min:-10,max:35}, yAxis:{}, series:[{type:'bar',values:[20]}] };
  assert.deepEqual(valueRange(chart), [-10,35]);
});
