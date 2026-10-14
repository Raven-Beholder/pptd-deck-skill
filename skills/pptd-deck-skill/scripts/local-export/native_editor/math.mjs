// Render only the bounded parser's own tree with native browser MathML.
const NS = "http://www.w3.org/1998/Math/MathML";
function element(tag, children = [], text) {
  const node = document.createElementNS(NS, tag);
  if (text !== undefined) node.textContent = text;
  node.append(...children);
  return node;
}
// MathML Core only guarantees mathvariant=normal. Use Unicode math
// alphabets so Chromium also displays the same variants as Office Math.
function alphabet(text, variant) {
  const offsets = {
    bold: [0x1d400, 0x1d41a, 0x1d7ce], italic: [0x1d434, 0x1d44e],
    "double-struck": [0x1d538, 0x1d552, 0x1d7d8],
    script: [0x1d49c, 0x1d4b6], fraktur: [0x1d504, 0x1d51e],
    "sans-serif": [0x1d5a0, 0x1d5ba, 0x1d7e2],
    monospace: [0x1d670, 0x1d68a, 0x1d7f6],
  }[variant];
  const exceptions = {
    italic: {h:"ℎ"},
    "double-struck": {C:"ℂ",H:"ℍ",N:"ℕ",P:"ℙ",Q:"ℚ",R:"ℝ",Z:"ℤ"},
    script: {B:"ℬ",E:"ℰ",F:"ℱ",H:"ℋ",I:"ℐ",L:"ℒ",M:"ℳ",R:"ℛ",e:"ℯ",g:"ℊ",o:"ℴ"},
    fraktur: {C:"ℭ",H:"ℌ",I:"ℑ",R:"ℜ",Z:"ℨ"},
  }[variant] || {};
  if (!offsets) return text;
  return [...text].map(char => {
    if (exceptions[char]) return exceptions[char];
    const code = char.codePointAt(0);
    if (code >= 65 && code <= 90) return String.fromCodePoint(offsets[0] + code - 65);
    if (code >= 97 && code <= 122) return String.fromCodePoint(offsets[1] + code - 97);
    if (offsets[2] && code >= 48 && code <= 57) return String.fromCodePoint(offsets[2] + code - 48);
    return char;
  }).join("");
}
export function mathTree(value, variant) {
  const children = value.children || [],
    visit = child => mathTree(child, variant);
  if (value.kind === "sequence") return element("mrow", children.map(visit));
  if (["symbol", "upright"].includes(value.kind)) {
    const token = element(
      value.kind === "upright"
        ? "mi"
        : /^\d$/.test(value.value)
          ? "mn"
          : /^\p{L}$/u.test(value.value)
            ? "mi"
            : "mo",
      [],
      alphabet(value.value, variant),
    );
    if (value.kind === "upright" || variant === "normal") token.setAttribute("mathvariant", "normal");
    if (token.localName === "mo") token.setAttribute("stretchy", "false");
    return token;
  }
  if (value.kind === "text") return element("mtext", [], value.value);
  if (value.kind === "space") {
    const space = element("mspace");
    space.setAttribute("width", value.value);
    return space;
  }
  if (value.kind === "fraction") {
    const fraction = element("mfrac", children.map(visit));
    if (value.value === "noBar") fraction.setAttribute("linethickness", "0");
    return fraction;
  }
  if (value.kind === "delimiter") {
    const [left, right] = value.value.split("\0");
    const fence = (text) => {
      const mo = element("mo", [], text);
      mo.setAttribute("fence", "true");
      mo.setAttribute("stretchy", "true");
      mo.setAttribute("symmetric", "true");
      return mo;
    };
    return element("mrow", [...(left ? [fence(left)] : []), ...children.map(visit), ...(right ? [fence(right)] : [])]);
  }
  if (value.kind === "matrix") {
    const table = element("mtable", children.map(row => element("mtr", row.children.map((cell, index) => {
      const td = element("mtd", [visit(cell)]);
      td.setAttribute("columnalign", value.value === "aligned" ? (index % 2 === 0 ? "right" : "left") : value.value === "cases" ? "left" : "center");
      return td;
    }))));
    table.setAttribute("columnspacing", value.value === "aligned" ? "0em" : "1em");
    table.setAttribute("rowspacing", "0.3em");
    return table;
  }
  if (["accent", "bar", "over", "under"].includes(value.kind)) {
    const under = value.kind === "under" || (value.kind === "bar" && value.value === "bot");
    const annotation = value.kind === "accent" || value.kind === "bar"
      ? element("mo", [], value.kind === "bar" ? (under ? "_" : "‾") : value.value)
      : visit(children[1]);
    const result = element(under ? "munder" : "mover", [visit(children[0]), annotation]);
    if (["accent", "bar"].includes(value.kind)) {
      result.setAttribute(under ? "accentunder" : "accent", "true");
      annotation.setAttribute("stretchy", "true");
    }
    return result;
  }
  if (value.kind === "root")
    return children[0].children?.length
      ? element("mroot", [visit(children[1]), visit(children[0])])
      : element("msqrt", [visit(children[1])]);
  if (value.kind === "script")
    return element({ _: "msub", "^": "msup", "_^": "msubsup" }[value.value], [
      visit(children[0]),
      ...(value.value.includes("_") ? [visit(children[1])] : []),
      ...(value.value.includes("^") ? [visit(children[2])] : []),
    ]);
  if (value.kind === "style") {
    const nextVariant = { mathrm: "normal", mathbf: "bold", mathit: "italic", mathbb: "double-struck", mathcal: "script", mathscr: "script", mathfrak: "fraktur", mathsf: "sans-serif", mathtt: "monospace" }[value.value];
    const style = element("mstyle", children.map(child => mathTree(child, nextVariant)));
    style.setAttribute("mathvariant", nextVariant);
    return style;
  }
  if (value.kind === "nary")
    return element("mrow", [
      element("munderover", [
        element("mo", [], value.value),
        visit(children[0]),
        visit(children[1]),
      ]),
      visit(children[2]),
    ]);
  throw new Error(`未支持的公式节点：${value.kind}`);
}
export function drawMath(expression) {
  const math = element("math", [mathTree(expression)]);
  math.setAttribute("display", "inline");
  return math;
}
