import { SHAPES } from '../skills/pptd-deck-skill/scripts/local-export/native_editor/shapes.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { PageDraft, SerialActions, newElement, previewWarnings, color, textStyle, canvasScale, moveLayer, resizeBounds, deleteElement, setTableCellText } from '../skills/pptd-deck-skill/scripts/local-export/native_editor/model.mjs';

test('editing mixed table cells preserves shorthand and object styles', () => {
  const table = { elementId: 'table', elementType: 'table', rows: [['plain', { text: 'styled', bold: true }]], columnWidths: [.5, .5], rowHeights: [.6] };
  setTableCellText(table, 0, 0, 'changed');
  setTableCellText(table, 0, 1, 'also changed');
  assert.deepEqual(table.rows, [['changed', { text: 'also changed', bold: true }]]);
  assert.ok(previewWarnings({ elements: [table] }, {}).some(w => /60.0%.*按比例/.test(w)));
  table.rowHeights = [1];
  assert.ok(!previewWarnings({ elements: [table] }, {}).some(w => /合计/.test(w)));
});

test('save follows an in-flight edit and a failed operation does not block future edits', async () => {
  const queue = new SerialActions(), events = [];
  let completeEdit;
  const gate = new Promise((resolve) => { completeEdit = resolve; });
  const edit = queue.run(async () => { events.push('edit-start'); await gate; events.push('edit-end'); });
  const save = queue.run(async () => { events.push('save'); });
  await Promise.resolve();
  assert.deepEqual(events, ['edit-start']);
  completeEdit(); await Promise.all([edit, save]);
  assert.deepEqual(events, ['edit-start', 'edit-end', 'save']);
  await assert.rejects(queue.run(() => { throw new Error('export rejected'); }), /export rejected/);
  await queue.run(() => events.push('next-edit'));
  assert.equal(events.at(-1), 'next-edit');
  const failedEdit = queue.run(() => { throw new Error('invalid property'); });
  const staleSave = queue.run(() => events.push('should not save stale state'));
  await assert.rejects(failedEdit, /invalid property/);
  await assert.rejects(staleSave, /前一项操作失败/);
  assert.equal(events.at(-1), 'next-edit');
  await queue.run(() => events.push('corrected edit'));
  assert.equal(events.at(-1), 'corrected edit');
});

test('undo/redo tracks unsaved state across saves and isolates independent page drafts', () => {
  const first = new PageDraft({ text: 'old', page: { elements: [], future: { keep: true } }, hash: 'h1', path: 'a.page' });
  const second = new PageDraft({ text: 'other', page: { elements: [] }, hash: 'h2', path: 'b.page' });
  const edited = structuredClone(first.page);
  edited.elements.push(newElement(edited, 'text'));
  first.change('edited', edited);
  edited.future.keep = false;
  assert.equal(first.page.future.keep, true);
  assert.equal(first.dirty, true);
  first.saved('h3', 'edited');
  assert.equal(first.dirty, false);
  first.undo();
  assert.equal(first.dirty, true);
  assert.equal(first.text, 'old');
  first.redo();
  assert.equal(first.dirty, false);
  assert.equal(first.hash, 'h3');
  assert.equal(second.text, 'other');
  first.undo(); first.change('branch', first.page);
  assert.equal(first.redo(), false);
});

test('new element IDs remain unique after deletion, insertion and unknown fields remain untouched', () => {
  const page = { elements: [{ elementId: 'text-1' }, { elementId: 'text-3' }], future: ['keep'] };
  const item = newElement(page, 'text');
  assert.equal(item.elementId, 'text-2');
  assert.deepEqual(page.future, ['keep']);
});

test('inserted tables and charts pass the real native preview and PPTX exporter', () => {
  const elements = ['table', 'chart'].map(kind => newElement({elements:[]}, kind));
  const check = spawnSync(globalThis.process.env.PYTHON || (globalThis.process.platform === 'win32' ? 'python' : 'python3'), ['-c', `
import json, sys, tempfile
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0, 'skills/pptd-deck-skill/scripts/local-export')
from native_cli import export
from native_preview import preview
elements = json.load(sys.stdin)
result = preview(dict(elements=elements), {})
assert not any('error' in item for item in result.values()), result
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'page.page').write_text(json.dumps(dict(elements=elements)))
    (root / 'deck.pptd').write_text('version: v2\\nsize: [960,540]\\npages: [page.page]\\n')
    export(root, root / 'output.pptx')
    with ZipFile(root / 'output.pptx') as archive:
        assert 'ppt/embeddings/chart1.xlsx' in archive.namelist()
        assert b'A1' in archive.read('ppt/slides/slide1.xml')
`], {input:JSON.stringify(elements), encoding:'utf8'});
  assert.equal(check.status, 0, check.stderr);
});

test('manual zoom stays stable and fit respects both slide dimensions', () => {
  assert.equal(canvasScale([960, 540], [984, 564]), 1);
  assert.equal(canvasScale([960, 540], [984, 294]), 0.5);
  assert.equal(canvasScale([960, 540], [300, 200], 2), 2);
  assert.equal(canvasScale([960, 540], [0, 0]), 0.02);
  assert.equal(canvasScale([960, 540], [984, 564], 10), 4);
});

test('layer moves preserve element data, animation references and undo history', () => {
  const value = { elements: [{ elementId: 'back', future: { keep: true } }, { elementId: 'middle' }, { elementId: 'front' }], animations: [{ target: 'back' }] };
  const draft = new PageDraft({ text: 'original', page: value });
  const next = structuredClone(draft.page); moveLayer(next, 'back', 1);
  assert.deepEqual(next.elements.map(e => e.elementId), ['middle', 'back', 'front']);
  assert.deepEqual(next.elements[1].future, { keep: true });
  assert.deepEqual(next.animations, value.animations);
  draft.change('reordered', next); draft.undo(); assert.deepEqual(draft.page, value);
  moveLayer(next, 'front', 1); assert.equal(next.elements.at(-1).elementId, 'front');
  assert.throws(() => moveLayer(next, 'missing', 1), /请选择/);
});

test('deletion removes only exact animation targets and undo restores both', () => {
  const page={elements:[{elementId:'a'},{elementId:'abc'}],animations:[{elementId:'a',effect:'fade-in'},{elementId:'abc',effect:'fade-out'}],future:{a:true}};
  const draft=new PageDraft({text:'before',page}),next=structuredClone(page);
  deleteElement(next,'a');draft.change('deleted',next);
  assert.deepEqual(next.animations,[{elementId:'abc',effect:'fade-out'}]);
  assert.deepEqual(next.elements,[{elementId:'abc'}]);assert.deepEqual(next.future,{a:true});
  draft.undo();assert.deepEqual(draft.page,page);
});

test('resizing rotated and flipped elements keeps the opposite corner anchored', () => {
  assert.deepEqual(resizeBounds([10,20,100,50], 0, null, [20,10]), [10,20,120,60]);
  const rotated = resizeBounds([10,20,100,50], 90, null, [-10,20]);
  assert.ok(rotated.every((value, i) => Math.abs(value - [-5,25,120,60][i]) < 1e-9));
  assert.deepEqual(resizeBounds([10,20,100,50], 0, [true,false], [-20,10]), [-10,20,120,60]);
  assert.deepEqual(resizeBounds([10,20,100,50], 0, null, [20,1], 'se', true), [10,20,120,60]);
  assert.equal(resizeBounds([10,20,100,50], 0, null, [-1000,-1000])[2], 1);
  const small = resizeBounds([10,20,100,50], 0, null, [-1000,-1000], 'se', true);
  assert.equal(small[2] / small[3], 2);
  assert.equal(small[3], 1);
});

test('theme resolution handles cycles and preview explicitly reports unrendered features', () => {
  const theme = { colors: { a: '$b', b: '$a', ink: '#123456' }, textStyles: { title: { fontSize: 32, bold: true } } };
  assert.equal(color('$a', theme), 'transparent');
  assert.equal(color('$ink', theme), '#123456');
  assert.equal(color('url(https://example.com)', theme), 'transparent');
  assert.equal(textStyle({ style: '$title', fontSize: 40 }, theme).fontSize, 40);
  assert.equal(textStyle({ style: '$title' }, theme).bold, true);
  const warnings = previewWarnings({ animations: [{}], elements: [{ elementType: 'chart' }, { elementType: 'image', crop: {} }] }, {});
  assert.ok(warnings.some((text) => text.includes('图表')));
  assert.ok(warnings.some((text) => text.includes('动画')));
  assert.ok(warnings.some((text) => text.includes('裁剪')));
});


test('all eight resize handles preserve the opposite edge including rotated flips',()=>{
  const b=[10,20,100,50];
  assert.deepEqual(resizeBounds(b,0,null,[-20,-10],'nw'),[-10,10,120,60]);
  assert.deepEqual(resizeBounds(b,0,null,[20,0],'w'),[30,20,80,50]);
  assert.deepEqual(resizeBounds(b,0,null,[0,-10],'n'),[10,10,100,60]);
  assert.deepEqual(resizeBounds(b,0,null,[20,-10],'ne'),[10,10,120,60]);
  assert.deepEqual(resizeBounds(b,0,null,[-20,10],'sw'),[-10,20,120,60]);
  const result=resizeBounds(b,90,[true,false],[10,20],'nw');
  assert.ok(result.every((n,i)=>Math.abs(n-[5,25,120,60][i])<1e-9));
});


test('every shape exposed by the picker exports as editable DrawingML',()=>{
  const items=SHAPES.map(([name],i)=>({elementId:`shape-${i}`,elementType:'shape',shapeName:name,bounds:[10,10,100,80],fill:{type:'solid',color:'#2563EB'}}));
  const result=spawnSync(globalThis.process.env.PYTHON || (globalThis.process.platform === 'win32' ? 'python' : 'python3'),['-c',`
import sys,json,tempfile
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
sys.path.insert(0,'skills/pptd-deck-skill/scripts/local-export')
from native_cli import export
items=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    (root/'deck.pptd').write_text('version: v2\\nsize: [960,540]\\npages: [page.yaml]\\n')
    (root/'page.yaml').write_text(json.dumps({'elements':items}))
    export(root,root/'deck.pptx')
    with ZipFile(root/'deck.pptx') as package:
        slide=E.fromstring(package.read('ppt/slides/slide1.xml'))
        presets=[g.attrib['prst'] for g in slide.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom')]
        assert presets==[item['shapeName'] for item in items]
`],{input:JSON.stringify(items),encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
});


test('theme deletion detects references across pages and other theme definitions', async () => {
  const { themeEntryReferences } = await import('../skills/pptd-deck-skill/scripts/local-export/native_editor/model.mjs');
  const theme = { colors: { accent1: '#6956DE', accent2: '$accent1' }, textStyles: { title: { color: '$accent1' } } };
  const pages = [{ background: { color: '$accent1' } }, { elements: [{ content: { style: '$title' } }] }];
  assert.deepEqual(themeEntryReferences(theme, pages, 'colors', 'accent1'), ['第 1 页', '主题 colors.accent2', '主题 textStyles.title']);
  assert.deepEqual(themeEntryReferences(theme, pages, 'textStyles', 'title'), ['第 2 页']);
  assert.deepEqual(themeEntryReferences(theme, pages, 'colors', 'accent2'), []);
  assert.deepEqual(theme.colors, { accent1: '#6956DE', accent2: '$accent1' });
});
