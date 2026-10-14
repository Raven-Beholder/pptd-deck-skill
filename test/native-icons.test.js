import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { ICONS } from '../skills/pptd-deck-skill/scripts/local-export/native_editor/icons.mjs';
test('independent icons cover every UI binding with uniform geometry', () => {
  const ui=fs.readFileSync(new URL('../skills/pptd-deck-skill/scripts/local-export/native_editor/ui.mjs',import.meta.url),'utf8');
  assert.equal(Object.keys(ICONS).length,43);
  for(const [name,icon] of Object.entries(ICONS)) {
    assert.equal(icon.viewBox,'0 0 24 24'); assert.ok(icon.children.length);
    for(const node of icon.children) {
      assert.ok(['path','rect','circle'].includes(node.tag));
      assert.equal(node.attrs['stroke-linecap'],'round');
      for(const [key,value] of Object.entries(node.attrs)) {
        assert.ok(['d','x','y','width','height','rx','cx','cy','r','fill','stroke','stroke-width','stroke-linecap','stroke-linejoin'].includes(key));
        assert.doesNotMatch(value,/[<>]|url\(|javascript:/i);
      }
    }
  }
  assert.match(ui,/\.\/icons\.mjs/);assert.doesNotMatch(ui,/reference-icons/);
});
