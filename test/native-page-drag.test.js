import test from 'node:test';
import assert from 'node:assert/strict';
import { pageDropIndex, pageScrollSpeed } from '../skills/pptd-deck-skill/scripts/local-export/native_editor/page-drag.mjs';

test('page insertion excludes the dragged page and distinguishes before/after', () => {
  const rows = [0, 1, 2, 3].map(i => ({ top: i * 110, bottom: i * 110 + 100 }));
  assert.equal(pageDropIndex(2, 270, rows), 2);
  assert.equal(pageDropIndex(2, 0, rows), 0);
  assert.equal(pageDropIndex(2, 90, rows), 1);
  assert.equal(pageDropIndex(0, 200, rows), 1);
  assert.equal(pageDropIndex(0, 9999, rows), 3);
  assert.equal(pageDropIndex(3, -20, rows), 0);
  assert.equal(pageDropIndex(0, 10, [{ top: 0, bottom: 50 }]), 0);
});

test('edge scrolling is continuous, bounded and stops in the middle', () => {
  assert.equal(pageScrollSpeed(300, 100, 500), 0);
  assert.equal(pageScrollSpeed(90, 100, 500), -18);
  assert.equal(pageScrollSpeed(510, 100, 500), 18);
  assert.ok(pageScrollSpeed(130, 100, 500) < 0);
  assert.ok(pageScrollSpeed(130, 100, 500) > -18);
  assert.ok(pageScrollSpeed(470, 100, 500) > 0);
  assert.equal(pageScrollSpeed(100, 100, 100), 0);
  assert.equal(pageScrollSpeed(120, 100, 140), 0);
});
