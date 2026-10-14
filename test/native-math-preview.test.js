import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mathTree} from '../skills/pptd-deck-skill/scripts/local-export/native_editor/math.mjs';

// Minimal DOM captures real MathML trees without relying on screenshots alone.
globalThis.document = {createElementNS(ns, tag) {
  return {namespaceURI:ns, localName:tag, children:[], attrs:{}, textContent:'',
    append(...children){this.children.push(...children);},
    setAttribute(name,value){this.attrs[name]=value;}};
}};
const symbol = value => ({kind:'symbol',value});
const walk = node => [node,...node.children.flatMap(walk)];

test('math alphabets render in Chromium and only explicit delimiters stretch',()=>{
  const bb = mathTree({kind:'style',value:'mathbb',children:[symbol('R')]});
  assert.equal(bb.children[0].textContent,'ℝ');
  assert.equal(mathTree(symbol('(')).attrs.stretchy,'false');
  const fence = mathTree({kind:'delimiter',value:'(\0)',children:[symbol('x')]});
  assert.equal(fence.children[0].attrs.stretchy,'true');
  assert.equal(fence.children[2].attrs.stretchy,'true');
});

test('every expanded parser example produces real MathML structural elements',()=>{
  const process=spawnSync(globalThis.process.env.PYTHON || (globalThis.process.platform === 'win32' ? 'python' : 'python3'),['-c',`
import sys,json
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0,'skills/pptd-deck-skill/scripts/local-export')
sys.path.insert(0,'skills/pptd-deck-skill/tests')
from test_native_math import EXAMPLES
from native_math import parse
print(json.dumps([asdict(parse(source).expression) for source in EXAMPLES]))
`],{encoding:'utf8',env:{...globalThis.process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  assert.equal(process.status,0,process.stderr);
  const trees=JSON.parse(process.stdout).map(value=>mathTree(value));
  const tags=index=>walk(trees[index]).map(node=>node.localName);
  assert.ok(tags(0).includes('mtext'));
  assert.ok(tags(2).includes('mroot') || tags(2).includes('msqrt'));
  assert.equal(tags(3).filter(tag=>tag==='mtr').length,2);
  assert.equal(tags(3).filter(tag=>tag==='mtd').length,4);
  assert.equal(tags(4).filter(tag=>tag==='mtd').length,4);
  assert.ok(tags(6).includes('mover'));
  assert.ok(tags(6).includes('munder'));
});
