import assert from 'node:assert/strict';
import test from 'node:test';
import { Playback } from '../skills/pptd-deck-skill/scripts/local-export/native_editor/playback.mjs';

const box = (opacity='1') => ({style:{opacity,visibility:''},animate:()=>({finished:new Promise(()=>{}),cancel(){}})});

test('player initializes entrances, completes click groups and restores previous state', t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const first=box('.5'),second=box(),boxes=new Map([['a',first],['b',second]]);
  const groups=[{click:true,events:[{shape_id:'a',effect:'fade-in',start:100,duration:200}]},
    {click:true,events:[{shape_id:'b',effect:'disappear',start:0,duration:1}]}];
  const player=new Playback(groups,boxes);
  assert.equal(first.style.visibility,'hidden');assert.equal(second.style.visibility,'');
  player.start();assert.equal(player.position,0);
  assert.equal(player.next(),true);t.mock.timers.tick(100);assert.equal(first.style.visibility,'visible');
  player.next();assert.equal(first.style.opacity,'.5');t.mock.timers.tick(1);assert.equal(second.style.visibility,'hidden');
  player.previous();assert.equal(second.style.visibility,'');assert.equal(first.style.visibility,'visible');
  player.previous();assert.equal(first.style.visibility,'hidden');assert.equal(player.previous(),false);
  player.dispose();
});

test('automatic group begins on entry and cancellation prevents delayed stale effects', t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const first=box(),player=new Playback([{click:false,events:[{shape_id:'a',effect:'appear',start:200,duration:1}]}],new Map([['a',first]]));
  player.start();assert.equal(player.position,1);assert.equal(first.style.visibility,'hidden');
  player.dispose();t.mock.timers.tick(500);assert.equal(first.style.visibility,'hidden');
});
