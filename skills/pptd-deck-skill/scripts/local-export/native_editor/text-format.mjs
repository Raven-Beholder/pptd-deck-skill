// Text-box and selection formatting. No third-party editor implementation.
import { color as themeColor } from "./model.mjs";

// CSSOM drops PPTD theme references such as color:$accent. Read declarations
// from the inert source attribute before asking the browser to paint them.
export function parseInlineStyles(source = "") {
  const result = {};
  for (const declaration of source.split(";")) {
    if (!declaration.trim()) continue;
    const colon = declaration.indexOf(":");
    if (colon < 1) throw new Error("无效的文字样式声明。");
    result[declaration.slice(0, colon).trim().toLowerCase()] =
      declaration.slice(colon + 1).trim();
  }
  return result;
}

const inlineStyle = (values) => Object.entries(values)
  .map(([key, value]) => `${key}: ${value}`).join("; ");
const cssKeys = {
  fontFamily: "font-family",
  fontSize: "font-size",
  color: "color",
  backgroundColor: "background-color",
  bold: "font-weight",
  italic: "font-style",
  align: "text-align",
  lineHeight: "line-height",
};
const semanticTags = {
  bold: "strong",
  italic: "em",
  underline: "u",
  strike: "s",
};
const tags = new Set([
  "P",
  "SPAN",
  "STRONG",
  "EM",
  "U",
  "S",
  "SUP",
  "SUB",
  "A",
  "BR",
]);

export function decoration(text, key) {
  const tag = semanticTags[key];
  if (typeof text !== "string") return false;
  return (
    new RegExp(`<${tag}(?:\\s|>)`, "i").test(text) ||
    (key === "bold" && /font-weight\s*:\s*(?:bold|700)/i.test(text)) ||
    (key === "italic" && /font-style\s*:\s*italic/i.test(text))
  );
}

export function formatText(content, key, value) {
  const source = String(content.text ?? ""),
    template = document.createElement("template");
  const html = /<\/?[a-zA-Z][^>]*>/.test(source);
  if (html) template.innerHTML = source;
  else {
    for (const line of source.replace(/\n$/, "").split("\n")) {
      const p = document.createElement("p");
      p.textContent = line;
      template.content.append(p);
    }
  }
  for (const node of template.content.querySelectorAll("*")) {
    if (
      !tags.has(node.tagName) ||
      [...node.attributes].some(
        (a) =>
          !(node.tagName !== "BR" && a.name === "style") &&
          !(node.tagName === "A" && a.name === "href"),
      )
    ) {
      throw new Error(
        "此文字包含格式工具尚未支持的标记或属性，请在源码中编辑。",
      );
    }
    if (cssKeys[key]) {
      const values = parseInlineStyles(node.getAttribute("style") || "");
      delete values[cssKeys[key]];
      if (Object.keys(values).length) node.setAttribute("style", inlineStyle(values));
      else node.removeAttribute("style");
    }
  }
  const tag = semanticTags[key];
  if (tag)
    for (const node of template.content.querySelectorAll(tag))
      node.replaceWith(...node.childNodes);
  if (["underline", "strike"].includes(key) && value) {
    // Wrap each paragraph independently: native rich text forbids nested <p>.
    for (const node of [...template.content.childNodes]) {
      const wrapper = document.createElement(tag);
      if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "P") {
        wrapper.append(...node.childNodes);
        node.append(wrapper);
      } else {
        node.replaceWith(wrapper);
        wrapper.append(node);
      }
    }
  }
  // Avoid rewriting unformatted plain text just to change its default font.
  if (html || ["underline", "strike"].includes(key))
    content.text = template.innerHTML;
  if (!["underline", "strike"].includes(key)) {
    if (value === null) delete content[key];
    else content[key] = value;
  }
}

// Selection formatting uses our own paragraph/run model. No vendor editor code.
const inlineCSS = new Set([
  "font-family",
  "font-size",
  "color",
  "background-color",
  "font-weight",
  "font-style",
  "letter-spacing",
]);
const blockCSS = new Set(["text-align", "line-height", "margin-top"]);
const escapeHTML = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function cssColor(value) {
  if (value === "transparent") return "#00000000";
  const rgb = value.match(
    /^rgba?\(\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/,
  );
  if (!rgb) return value;
  return (
    "#" +
    rgb
      .slice(1, 4)
      .map((n) => Math.round(Number(n)).toString(16).padStart(2, "0"))
      .join("") +
    (rgb[4] === undefined
      ? ""
      : Math.round(Number(rgb[4]) * 255)
          .toString(16)
          .padStart(2, "0"))
  );
}
export function readParagraphs(source) {
  const root = document.createElement("template");
  if (typeof source === "string") {
    if (/<\/?[a-zA-Z][^>]*>/.test(source)) root.innerHTML = source;
    else
      for (const line of source.replace(/\n$/, "").split("\n")) {
        const p = document.createElement("p");
        p.textContent = line;
        root.content.append(p);
      }
  } else
    root.content.append(
      ...[...source.childNodes].map((n) => n.cloneNode(true)),
    );
  const paragraphs = [];
  let paragraph;
  const ensure = () =>
    (paragraph ||=
      (paragraphs.push({ style: {}, runs: [] }), paragraphs.at(-1)));
  function visit(node, inherited = {}) {
    if (node.nodeType === 3) {
      // Formatting whitespace between <p> blocks is not a paragraph. Keep
      // whitespace within a paragraph and explicit <br> / empty <p> intact.
      if (!paragraph && !node.data.trim()) return;
      ensure().runs.push({
        ...inherited,
        style: { ...inherited.style },
        text: node.data,
      });
      return;
    }
    if (node.nodeType !== 1) return;
    const tag = node.tagName;
    if (!tags.has(tag) && !["DIV", "B", "I", "STRIKE"].includes(tag))
      throw new Error(`文字编辑不支持 ${tag} 标记，请使用源码编辑。`);
    if (
      [...node.attributes].some(
        (a) =>
          !(a.name === "style" && tag !== "BR") &&
          !(a.name === "href" && tag === "A") &&
          !(
            typeof source !== "string" &&
            tag === "SPAN" &&
            a.name === "data-inherited-highlight"
          ) &&
          !(
            typeof source !== "string" &&
            tag !== "BR" &&
            a.name === "data-pptd-theme-style"
          ),
      )
    )
      throw new Error(`文字编辑不支持 ${tag} 的附加属性，请使用源码编辑。`);
    const next = { ...inherited, style: { ...inherited.style } };
    const block = {};
    const values = parseInlineStyles(node.getAttribute("style") || "");
    if (typeof source !== "string" && node.hasAttribute("data-pptd-theme-style")) {
      const references = JSON.parse(node.getAttribute("data-pptd-theme-style"));
      for (const [key, [reference, painted]] of Object.entries(references)) {
        if (["color", "background-color"].includes(key) &&
            typeof reference === "string" && reference.startsWith("$") &&
            cssColor(values[key] || "") === cssColor(painted))
          values[key] = reference;
      }
    }
    for (const [key, raw] of Object.entries(values)) {
      // A view-only wrapper paints the text-box default behind glyphs. It must
      // not become an explicit run style when the edited DOM is serialized.
      if (
        typeof source !== "string" &&
        node.hasAttribute("data-inherited-highlight") &&
        key === "background-color"
      )
        continue;
      if (!inlineCSS.has(key) && !blockCSS.has(key))
        throw new Error(`文字编辑不支持 ${key} 样式。`);
      const value = raw;
      if (inlineCSS.has(key))
        next.style[key] = key.includes("color") ? cssColor(value) : value;
      else block[key] = value;
    }
    if (["B", "STRONG"].includes(tag)) next.style["font-weight"] = "700";
    if (["I", "EM"].includes(tag)) next.style["font-style"] = "italic";
    if (tag === "U") next.underline = true;
    if (["S", "STRIKE"].includes(tag)) next.strike = true;
    if (["SUP", "SUB"].includes(tag)) next.script = tag.toLowerCase();
    if (tag === "A") {
      const href = node.getAttribute("href");
      if (!/^(https?:\/\/|mailto:)\S+$/.test(href || ""))
        throw new Error("不支持的文字链接。");
      next.href = href;
    }
    if (["P", "DIV"].includes(tag)) {
      paragraph = { style: block, runs: [] };
      paragraphs.push(paragraph);
      for (const child of node.childNodes) visit(child, next);
      paragraph = null;
    } else if (tag === "BR") ensure().runs.push({ ...next, text: null });
    else for (const child of node.childNodes) visit(child, next);
  }
  for (const child of root.content.childNodes) visit(child);
  return paragraphs.length ? paragraphs : [{ style: {}, runs: [] }];
}
export function writeParagraphs(paragraphs, { inheritedHighlight, theme } = {}) {
  const style = (values) => {
    const painted = { ...values }, references = {};
    if (theme) {
      for (const key of ["color", "background-color"]) {
        if (typeof painted[key] === "string" && painted[key].startsWith("$")) {
          const reference = painted[key];
          painted[key] = themeColor(reference, theme);
          references[key] = [reference, painted[key]];
        }
      }
    }
    const css = inlineStyle(painted);
    const metadata = Object.keys(references).length
      ? ` data-pptd-theme-style="${escapeHTML(JSON.stringify(references))}"` : "";
    return css ? `${metadata} style="${escapeHTML(css)}"` : "";
  };
  const compact = (runs) => {
    const result = [];
    for (const run of runs) {
      const last = result.at(-1),
        signature = (value) =>
          JSON.stringify({
            ...value,
            text: undefined,
            style: Object.fromEntries(Object.entries(value.style || {}).sort()),
          });
      if (
        last &&
        last.text !== null &&
        run.text !== null &&
        signature(last) === signature(run)
      )
        last.text += run.text;
      else result.push({ ...run });
    }
    return result;
  };
  return paragraphs
    .map(
      (p) =>
        `<p${style(p.style)}>${compact(p.runs)
          .map((run) => {
            let text = run.text === null ? "<br>" : escapeHTML(run.text);
            if (Object.keys(run.style || {}).length)
              text = `<span${style(run.style)}>${text}</span>`;
            if (
              inheritedHighlight &&
              !["transparent", "#00000000"].includes(inheritedHighlight) &&
              run.text !== null &&
              !run.style?.["background-color"]
            )
              text = `<span data-inherited-highlight="true"${style({ "background-color": inheritedHighlight })}>${text}</span>`;
            if (run.underline) text = `<u>${text}</u>`;
            if (run.strike) text = `<s>${text}</s>`;
            if (run.script) text = `<${run.script}>${text}</${run.script}>`;
            if (run.href)
              text = `<a href="${escapeHTML(run.href)}">${text}</a>`;
            return text;
          })
          .join("")}</p>`,
    )
    .join("");
}
function runFormat(run, key, value) {
  const result = { ...run, style: { ...run.style } };
  if (["underline", "strike"].includes(key)) result[key] = Boolean(value);
  else if (key === "script") {
    if (![null, "sup", "sub"].includes(value))
      throw new Error("无效的上下标格式。");
    if (value) result.script = value;
    else delete result.script;
  } else {
    const property = cssKeys[key];
    if (!property || !inlineCSS.has(property))
      throw new Error("该选项暂不支持局部文字编辑。");
    if (key === "fontSize") {
      if (!Number.isFinite(Number(value)) || value < 1 || value > 4000)
        throw new Error("字号必须为 1–4000。");
      value = `${Number(value)}px`;
    }
    if (key === "fontFamily") {
      if (typeof value === "object")
        value = [...new Set([value.latin, value.ea].filter(Boolean))].join(
          ", ",
        );
      if (!String(value).trim() || /[;<>\r\n]/.test(value))
        throw new Error("字体名称无效。");
    }
    if (key === "bold") value = value ? "700" : "400";
    if (key === "italic") value = value ? "italic" : "normal";
    result.style[property] = String(value);
  }
  return result;
}
export function formatSelection(paragraphs, start, end, changes) {
  let offset = 0;
  return paragraphs.map((p) => ({
    ...p,
    runs: p.runs.flatMap((run) => {
      if (run.text === null) return [{ ...run }];
      const from = Math.max(0, start - offset),
        to = Math.min(run.text.length, end - offset);
      offset += run.text.length;
      if (from >= to) return [{ ...run, style: { ...run.style } }];
      const parts = [];
      if (from) parts.push({ ...run, text: run.text.slice(0, from) });
      let middle = { ...run, text: run.text.slice(from, to) };
      for (const [key, value] of Object.entries(changes))
        middle = runFormat(middle, key, value);
      parts.push(middle);
      if (to < run.text.length)
        parts.push({ ...run, text: run.text.slice(to) });
      return parts;
    }),
  }));
}
export function textBookmark(root) {
  const selection = getSelection();
  if (
    !selection?.rangeCount ||
    !root.contains(selection.anchorNode) ||
    !root.contains(selection.focusNode)
  )
    return null;
  const offset = (node, pos) => {
    const range = document.createRange();
    range.selectNodeContents(root);
    range.setEnd(node, pos);
    return range.toString().length;
  };
  return {
    anchor: offset(selection.anchorNode, selection.anchorOffset),
    focus: offset(selection.focusNode, selection.focusOffset),
  };
}
export function restoreTextBookmark(root, bookmark) {
  if (!bookmark) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT),
    nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  function point(offset) {
    for (const node of nodes) {
      if (offset <= node.length) return [node, offset];
      offset -= node.length;
    }
    return nodes.length ? [nodes.at(-1), nodes.at(-1).length] : [root, 0];
  }
  const selection = getSelection();
  root.focus();
  selection.setBaseAndExtent(
    ...point(bookmark.anchor),
    ...point(bookmark.focus),
  );
}

export class TextEditingSession {
  constructor(root, source, onChange, onFinish, options = {}) {
    this.events = new AbortController();
    const listen = (type, handler) =>
      root.addEventListener(type, handler, { signal: this.events.signal });
    this.root = root;
    this.onChange = onChange;
    this.onFinish = onFinish;
    this.initial = writeParagraphs(readParagraphs(source));
    this.viewOptions = { inheritedHighlight: options.inheritedHighlight, theme: options.theme };
    this.undo = [];
    this.redo = [];
    this.pending = {};
    if (!options.preserveDOM)
      root.innerHTML = writeParagraphs(
        readParagraphs(source),
        this.viewOptions,
      );
    root.contentEditable = "true";
    root.classList.add("editing-text");
    this.bookmark = { anchor: 0, focus: 0 };
    this.composing = false;
    listen("pointerdown", (e) => {
      e.stopPropagation();
      this.pending = {};
    });
    listen("click", (e) => {
      if (e.target.closest("a")) e.preventDefault();
    });
    listen("beforeinput", (e) => {
      if (e.inputType === "historyUndo" || e.inputType === "historyRedo") {
        e.preventDefault();
        this.travel(e.inputType === "historyUndo" ? "undo" : "redo");
        return;
      }
      if (!this.composing) {
        this.before = this.snapshot();
        this.push(this.before);
      }
    });
    listen("compositionstart", () => {
      this.before = this.snapshot();
      this.push(this.before);
      this.composing = true;
    });
    listen("compositionend", () => {
      this.composing = false;
      this.input();
    });
    listen("input", () => {
      if (!this.composing) this.input();
    });
    listen("keydown", (e) => {
      e.stopPropagation();
      if (
        [
          "ArrowLeft",
          "ArrowRight",
          "ArrowUp",
          "ArrowDown",
          "Home",
          "End",
        ].includes(e.key)
      )
        this.pending = {};
      const key = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && ["b", "i", "u"].includes(key)) {
        e.preventDefault();
        const name = { b: "bold", i: "italic", u: "underline" }[key];
        this.apply({ [name]: !this.state()[name] });
      } else if ((e.metaKey || e.ctrlKey) && ["z", "y"].includes(key)) {
        e.preventDefault();
        this.travel(key === "y" || e.shiftKey ? "redo" : "undo");
      } else if (e.key === "Escape") {
        e.preventDefault();
        this.onFinish(false);
      } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        this.onFinish(true);
      } else if ((e.metaKey || e.ctrlKey) && key === "s") {
        e.preventDefault();
        this.onFinish(true, true);
      }
    });
    listen("paste", (e) => {
      e.preventDefault();
      this.capture();
      this.before = this.snapshot();
      this.push(this.before);
      restoreTextBookmark(root, this.bookmark);
      const range = getSelection().getRangeAt(0);
      range.deleteContents();
      const node = document.createTextNode(
        e.clipboardData.getData("text/plain"),
      );
      range.insertNode(node);
      range.setStartAfter(node);
      range.collapse(true);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      this.input();
    });
    restoreTextBookmark(root, this.bookmark);
  }
  html() {
    return writeParagraphs(readParagraphs(this.root));
  }
  get dirty() {
    return this.html() !== this.initial;
  }
  capture() {
    const next = textBookmark(this.root);
    if (next) this.bookmark = next;
    return this.bookmark;
  }
  snapshot() {
    return { html: this.html(), bookmark: { ...this.capture() } };
  }
  push(value) {
    this.undo.push(value);
    if (this.undo.length > 50) this.undo.shift();
    this.redo = [];
  }
  input() {
    const after = this.capture();
    if (Object.keys(this.pending).length && this.before) {
      const start = Math.min(
          this.before.bookmark.anchor,
          this.before.bookmark.focus,
        ),
        end = Math.max(after.anchor, after.focus);
      if (end > start)
        this.root.innerHTML = writeParagraphs(
          formatSelection(readParagraphs(this.root), start, end, this.pending),
          this.viewOptions,
        );
      restoreTextBookmark(this.root, after);
    }
    this.onChange();
  }
  apply(changes) {
    for (const [key, value] of Object.entries(changes))
      runFormat({ style: {} }, key, value);
    this.capture();
    const { anchor, focus } = this.bookmark;
    if (anchor === focus) {
      this.pending = { ...this.pending, ...changes };
      restoreTextBookmark(this.root, this.bookmark);
      this.onChange();
      return;
    }
    const html = writeParagraphs(
      formatSelection(
        readParagraphs(this.root),
        Math.min(anchor, focus),
        Math.max(anchor, focus),
        changes,
      ),
      this.viewOptions,
    );
    this.push(this.snapshot());
    this.root.innerHTML = html;
    restoreTextBookmark(this.root, this.bookmark);
    this.onChange();
  }
  travel(command) {
    const from = this[command],
      to = this[command === "undo" ? "redo" : "undo"],
      value = from.pop();
    if (!value) return;
    to.push(this.snapshot());
    this.root.innerHTML = writeParagraphs(
      readParagraphs(value.html),
      this.viewOptions,
    );
    this.bookmark = value.bookmark;
    this.pending = {};
    restoreTextBookmark(this.root, this.bookmark);
    this.onChange();
  }
  state() {
    const { anchor, focus } = this.capture(),
      start = Math.min(anchor, focus),
      end = Math.max(anchor, focus);
    let offset = 0;
    const selected = [];
    for (const p of readParagraphs(this.root))
      for (const run of p.runs) {
        if (run.text === null) continue;
        const last = offset + run.text.length;
        if (
          start === end
            ? start >= offset && start <= last
            : last > start && offset < end
        )
          selected.push(run);
        offset = last;
      }
    const result = {};
    for (const key of [
      "fontFamily",
      "fontSize",
      "color",
      "backgroundColor",
      "bold",
      "italic",
      "underline",
      "strike",
    ]) {
      const values = selected.map((r) =>
        key === "bold"
          ? r.style["font-weight"] === undefined
            ? undefined
            : /^(bold|700)$/.test(r.style["font-weight"])
          : key === "italic"
            ? r.style["font-style"] === undefined
              ? undefined
              : r.style["font-style"] === "italic"
            : key === "underline" || key === "strike"
              ? Boolean(r[key])
              : r.style[cssKeys[key]],
      );
      result[key] = values.every((v) => v === values[0]) ? values[0] : "mixed";
      if (result[key] === undefined && key === "bold")
        result[key] = Number(getComputedStyle(this.root).fontWeight) >= 600;
      if (result[key] === undefined && key === "italic")
        result[key] = getComputedStyle(this.root).fontStyle === "italic";
    }
    return start === end ? { ...result, ...this.pending } : result;
  }
  close() {
    this.events.abort();
    this.root.contentEditable = "false";
    this.root.classList.remove("editing-text");
  }
}

// Replace a text range without flattening the paragraph/run styles around it.
// Offsets use the same UTF-16 units as DOM Range and textBookmark.
export function replaceSelection(paragraphs, start, end, text) {
  let offset = 0,
    inserted = false;
  const result = paragraphs.map((p) => ({
    ...p,
    runs: p.runs.flatMap((run) => {
      if (run.text === null) return [{ ...run }];
      const base = offset,
        limit = offset + run.text.length;
      offset = limit;
      if (limit < start || base > end) return [{ ...run }];
      const before = Math.max(0, Math.min(run.text.length, start - base));
      const after = Math.max(0, Math.min(run.text.length, end - base));
      const parts = [];
      if (before) parts.push({ ...run, text: run.text.slice(0, before) });
      if (!inserted) {
        parts.push({ ...run, text });
        inserted = true;
      }
      if (after < run.text.length)
        parts.push({ ...run, text: run.text.slice(after) });
      return parts;
    }),
  }));
  if (!result.length) result.push({ style: {}, runs: [] });
  if (!inserted) result.at(-1).runs.push({ text, style: {} });
  return result;
}
