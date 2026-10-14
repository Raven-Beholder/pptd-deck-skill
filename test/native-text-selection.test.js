import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  formatSelection,
  replaceSelection,
  writeParagraphs,
} from "../skills/pptd-deck-skill/scripts/local-export/native_editor/text-format.mjs";
const sample = () => [
  {
    style: { "text-align": "center" },
    runs: [{ text: "完全本地离线", style: { "font-size": "48px" } }],
  },
];
test("inherited highlight is view-only and explicit run highlights win", () => {
  const paragraphs = [
    {
      style: {},
      runs: [
        { text: "default", style: {} },
        { text: "explicit", style: { "background-color": "#00ff00" } },
        { text: "clear", style: { "background-color": "#00000000" } },
      ],
    },
  ];
  const view = writeParagraphs(paragraphs, { inheritedHighlight: "#ffff00" });
  assert.equal((view.match(/data-inherited-highlight/g) || []).length, 1);
  assert.match(view, /background-color: #ffff00">default<\/span>/);
  assert.match(view, /background-color: #00ff00">explicit<\/span>/);
  assert.match(view, /background-color: #00000000">clear<\/span>/);
  assert.doesNotMatch(
    writeParagraphs(paragraphs),
    /data-inherited-highlight|#ffff00/,
  );
  assert.doesNotMatch(
    writeParagraphs(paragraphs, { inheritedHighlight: "transparent" }),
    /data-inherited-highlight/,
  );
});
test("selection formatting preserves outside text and paragraph properties", () => {
  const source = sample(),
    result = formatSelection(source, 0, 2, {
      bold: true,
      fontFamily: "Arial",
      color: "#123456",
    });
  assert.equal(result[0].runs[0].text, "完全");
  assert.equal(result[0].runs[0].style["font-weight"], "700");
  assert.equal(result[0].runs[1].text, "本地离线");
  assert.equal(result[0].runs[1].style["font-weight"], undefined);
  assert.equal(source[0].runs.length, 1);
  assert.equal(result[0].style["text-align"], "center");
});
test("cross-paragraph formatting keeps breaks, links, emoji and unrelated marks", () => {
  const paragraphs = [
    {
      style: {},
      runs: [
        {
          text: "A😀B",
          style: {},
          underline: true,
          href: "https://example.com",
        },
      ],
    },
    {
      style: {},
      runs: [
        { text: null, style: {} },
        { text: "中文C", style: {}, strike: true },
      ],
    },
  ];
  const result = formatSelection(paragraphs, 1, 6, {
    underline: false,
    fontSize: 30,
  });
  assert.deepEqual(
    result[0].runs.map((r) => r.text),
    ["A", "😀B"],
  );
  assert.equal(result[0].runs[1].underline, false);
  assert.equal(result[0].runs[1].href, "https://example.com");
  assert.equal(result[1].runs[0].text, null);
  assert.equal(result[1].runs[1].text, "中文");
  assert.equal(result[1].runs[1].strike, true);
  assert.equal(result[1].runs[2].text, "C");
});
test("repeated formatting compacts adjacent equivalent runs without mutating input", () => {
  let result = formatSelection(sample(), 0, 2, { bold: true });
  result = formatSelection(result, 2, 6, { bold: true });
  const html = writeParagraphs(result);
  assert.equal((html.match(/<span/g) || []).length, 1);
  assert.equal(result[0].runs[0].text, "完全");
  assert.throws(() => formatSelection(sample(), 0, 2, { fontSize: 0 }), /字号/);
  assert.throws(
    () => formatSelection(sample(), 0, 2, { fontFamily: "Arial; color:red" }),
    /字体/,
  );
});
test("selection output round-trips through native rich-text and DrawingML writer", () => {
  const html = writeParagraphs(
    formatSelection(sample(), 0, 2, {
      bold: true,
      italic: true,
      underline: true,
      fontSize: 30,
      color: "#123456",
      fontFamily: "Arial",
    }),
  );
  const result = spawnSync(
    globalThis.process.env.PYTHON || (globalThis.process.platform === "win32" ? "python" : "python3"),
    [
      "-c",
      `
import sys,json,tempfile
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
sys.path.insert(0,'skills/pptd-deck-skill/scripts/local-export')
from native_cli import export
from native_text import RichText
text=json.load(sys.stdin)
parsed=RichText(text, {})
runs=parsed.paragraphs[0][1]
assert runs[0][0]=='完全' and runs[0][1]['bold'] and runs[0][1]['fontSize']==30
assert runs[1][0]=='本地离线' and not runs[1][1].get('bold')
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 (root/'deck.pptd').write_text('version: v2\\nsize: [960,540]\\npages: [one.page]\\n')
 (root/'one.page').write_text(json.dumps({'elements':[{'elementId':'t','elementType':'text','bounds':[20,20,800,200],'content':{'text':text,'fontFamily':'Arial','fontSize':48,'color':'#333333'}}]}))
 export(root,root/'out.pptx')
 with ZipFile(root/'out.pptx') as archive:
  doc=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
  ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
  rs=doc.findall('.//a:r',ns)
  assert [r.find('a:t',ns).text for r in rs]==['完全','本地离线']
  first=rs[0].find('a:rPr',ns)
  assert first.get('b')=='1' and first.get('sz')=='3000' and first.get('u')=='sng'
  assert first.find('a:solidFill/a:srgbClr',ns).get('val')=='123456'
  assert rs[1].find('a:rPr',ns).get('b')!='1'
`,
    ],
    { input: JSON.stringify(html), encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
});

test("inline formula replacement retains surrounding styles, links and UTF-16 offsets", () => {
  const source = [
    {
      style: { "text-align": "center" },
      runs: [
        {
          text: "A😀B",
          style: { "font-weight": "700" },
          href: "https://example.com",
        },
        { text: "中文C", style: { color: "#123456" } },
      ],
    },
  ];
  const changed = replaceSelection(source, 1, 5, String.raw`\(x^2\)`);
  assert.equal(
    changed[0].runs.map((r) => r.text).join(""),
    String.raw`A\(x^2\)文C`,
  );
  assert.equal(changed[0].runs.at(-1).style.color, "#123456");
  assert.equal(changed[0].runs[1].href, "https://example.com");
  assert.equal(source[0].runs[0].text, "A😀B");
  assert.equal(changed[0].style["text-align"], "center");
  assert.equal(
    writeParagraphs(replaceSelection([{ style: {}, runs: [] }], 0, 0, "x")),
    "<p>x</p>",
  );
  assert.equal(
    writeParagraphs(replaceSelection(sample(), 6, 6, "!")),
    '<p style="text-align: center"><span style="font-size: 48px">完全本地离线!</span></p>',
  );
});
test("superscript and subscript replace each other and can return to baseline", () => {
  let changed = formatSelection(sample(), 0, 2, { script: "sup" });
  assert.match(writeParagraphs(changed), /<sup>/);
  changed = formatSelection(changed, 0, 2, { script: "sub" });
  assert.doesNotMatch(writeParagraphs(changed), /<sup>/);
  assert.match(writeParagraphs(changed), /<sub>/);
  changed = formatSelection(changed, 0, 2, { script: null });
  assert.doesNotMatch(writeParagraphs(changed), /<(sup|sub)>/);
});
