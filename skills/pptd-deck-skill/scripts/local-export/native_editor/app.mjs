import { slideImage as exportSlideImage, rasterImage } from "./images.mjs";
import {
  installIcons,
  setButtonIcon,
  icon,
  Popup,
  enhanceControls,
} from "./ui.mjs";
import {
  PageDraft,
  SerialActions,
  clone,
  color,
  textStyle,
  newElement,
  previewWarnings,
  canvasScale,
  moveLayer,
  resizeBounds,
  deleteElement,
  themeEntryReferences,
} from "./model.mjs";
import { drawChart } from "./charts.mjs";
import {
  decoration,
  formatText,
  TextEditingSession,
  readParagraphs,
  writeParagraphs,
  formatSelection,
  replaceSelection,
  restoreTextBookmark,
} from "./text-format.mjs";
import { SHAPES, drawShape, drawLine } from "./shapes.mjs";
import { drawMath } from "./math.mjs";
import { Playback } from "./playback.mjs";

const $ = (id) => document.getElementById(id);
const controls = enhanceControls();
const token =
  location.hash.slice(1) || sessionStorage.getItem("pptd-session") || "";
if (token) sessionStorage.setItem("pptd-session", token);
// Keep the capability out of copied URLs and referrers after bootstrap.
history.replaceState(null, "", location.pathname);
let project,
  drafts = [],
  current = 0,
  selected = null,
  busy = false,
  scale = 1,
  pendingControls = false;
const images = new Map();
const actions = new SerialActions();
let renderVersion = 0,
  previews = {};
let selectedIds = new Set(),
  clipboard = null,
  pageSelection = new Set(),
  pageUndo = [],
  pageRedo = [];
let replacingShape = false;
let textSession = null;
let historyUndo = [],
  historyRedo = [];
let zoom = null;
let savedTheme = "{}",
  themeUndo = [],
  themeRedo = [],
  formulaValid = false;
const formulaCache = new Map();
const themeDirty = () =>
  JSON.stringify(project?.deck.theme || {}) !== savedTheme;
const previewCache = new Map();
let thumbnailObserver;
const thumbnailQueue = [];
let thumbnailWorkers = 0;
const page = () => drafts[current];
const element = () =>
  page()?.page.elements.find((item) => item.elementId === selected);
const hasPendingSource = () => page() && $("source").value !== page().text;

async function api(path, body, binary = false) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(project?.projectId ? { "X-PPTD-Project": project.projectId } : {}),
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const result = await response.json();
    throw new Error(result.error || `HTTP ${response.status}`);
  }
  return binary ? response.blob() : response.json();
}

function status(message) {
  $("status").textContent = message;
}
function showError(error) {
  const dialog = document.querySelector("dialog[open]");
  if (dialog) {
    let message = dialog.querySelector(".dialog-error");
    if (!message) {
      message = document.createElement("p");
      message.className = "dialog-error";
      message.setAttribute("role", "alert");
      dialog.append(message);
    }
    message.textContent = error.message;
    return;
  }
  $("error").textContent = error.message;
  $("error").hidden = false;
}
function action(task) {
  return actions
    .run(async () => {
      busy = true;
      $("error").hidden = true;
      document
        .querySelectorAll(".dialog-error")
        .forEach((node) => node.remove());
      refreshControls();
      try {
        await task();
      } finally {
        busy = false;
        refreshControls();
      }
    })
    .catch(showError);
}
function refreshControls() {
  // Toolbar clicks queue behind an in-flight property edit instead of vanishing.
  document.querySelectorAll("button").forEach((button) => {
    if (!button.closest(".context-menu,.choice-popup"))
      button.disabled = !project;
  });
  if (!project) return;
  $("properties").disabled = busy || !element();
  $("text-controls").disabled = element()?.elementType !== "text";
  document.querySelectorAll("#data-cells input").forEach((input) => {
    input.disabled = busy;
  });
  $("source").disabled = busy;
  $("notes").disabled = busy;
  const themeActive = !$("theme-panel").hidden && !$("inspector").hidden;
  $("undo").disabled =
    !busy &&
    !(textSession
      ? textSession.undo.length
      : themeActive
        ? themeUndo.length
        : historyUndo.length);
  $("redo").disabled =
    !busy &&
    !(textSession
      ? textSession.redo.length
      : themeActive
        ? themeRedo.length
        : historyRedo.length);
  $("duplicate").disabled = $("delete").disabled = !element();
  $("delete-selection").disabled = !element();
  $("layer-up").disabled =
    !element() || page().page.elements.at(-1)?.elementId === selected;
  $("layer-down").disabled =
    !element() || page().page.elements[0]?.elementId === selected;
  $("save").disabled =
    !busy &&
    !page().dirty &&
    !themeDirty() &&
    !hasPendingSource() &&
    !pendingControls &&
    !textSession?.dirty;
  $("preview-prev").disabled = previewIndex === 0 && !player?.position;
  $("preview-next").disabled = presentationLoading;
  for (const id of ["shape-replace", "shape-fill", "shape-fill-options"])
    $(id).disabled = element()?.elementType !== "shape";
  $("formula-apply").disabled = busy || !formulaValid;
  for (const id of [
    "export-download",
    "export-format",
    "export-destination",
    "export-directory",
    "export-filename",
  ])
    $(id).disabled = busy;
  $("export-transition").disabled = busy || $("export-format").value !== "pptx";
  document
    .querySelectorAll(
      "#theme-panel input,#theme-panel textarea,#style-dialog input,#color-dialog input",
    )
    .forEach((input) => (input.disabled = busy));
  if ($("theme-delete-dialog").open && deletingThemeEntry)
    $("theme-delete-confirm").disabled = busy || themeDeleteReferences(deletingThemeEntry.kind, deletingThemeEntry.name).length > 0;
  controls.sync();
}

function markPendingControl() {
  pendingControls = true;
  status("属性输入尚未提交");
  refreshControls();
}

function download(blob, name) {
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function applySource() {
  if (!hasPendingSource()) return;
  const text = $("source").value;
  const result = await api("/api/parse", { text });
  page().change(text, result.page);
  recordHistory({ kind: "pages", drafts: [page()] });
}

async function edit(update, options = {}) {
  await applySource();
  const value = clone(page().page);
  update(value);
  const result = await api("/api/serialize", { page: value });
  if (page().text !== result.text) {
    page().change(result.text, value);
    recordHistory({ kind: "pages", drafts: [page()] });
  }
  if (options.render !== false) render();
  // Keep the source editor synchronized even while retaining the gesture DOM.
  // Otherwise the next edit would treat its old text as a user-authored change.
  else $("source").value = page().text;
}

function paint(target, fill) {
  target.style.background = "transparent";
  if (fill?.type === "solid")
    target.style.background = color(fill.color, project.deck.theme);
  if (fill?.type === "gradient" && Array.isArray(fill.stops)) {
    const stops = fill.stops
      .map(
        (stop) =>
          `${color(stop.color, project.deck.theme)} ${Number(stop.position) * 100}%`,
      )
      .join(",");
    target.style.background =
      fill.gradientType === "radial"
        ? `radial-gradient(circle,${stops})`
        : `linear-gradient(${Number(fill.angle || 0) + 90}deg,${stops})`;
  }
  if (fill?.type === "image")
    imageURL(fill.src)
      .then((url) => {
        target.style.backgroundImage = `url("${url}")`;
        target.style.backgroundPosition = "center";
        target.style.backgroundRepeat = "no-repeat";
        target.style.backgroundSize =
          { contain: "contain", cover: "cover", fill: "100% 100%" }[
            fill.fit?.mode
          ] || "cover";
      })
      .catch(() => {
        target.dataset.previewError = "背景图片无法加载";
      });
}

// Never insert project HTML into the live document. Rebuild a small allowlist
// from an inert parse; links, event handlers, images and remote resources vanish.
function richText(source, target, highlight) {
  const allowed = new Set([
    "P",
    "SPAN",
    "STRONG",
    "EM",
    "U",
    "S",
    "SUB",
    "SUP",
    "BR",
    "A",
  ]);
  const styles = new Set([
    "color",
    "background-color",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "line-height",
    "letter-spacing",
    "text-align",
    "margin-top",
  ]);
  const textNode = (text, inheritedHighlight = highlight) => {
    if (/\\\([\s\S]*?\\\)/.test(text))
      return formulaText(text, inheritedHighlight);
    if (!inheritedHighlight || inheritedHighlight === "transparent")
      return document.createTextNode(text);
    const span = document.createElement("span");
    span.style.backgroundColor = inheritedHighlight;
    span.textContent = text;
    return span;
  };
  if (!/<\/?[a-zA-Z][^>]*>/.test(source)) {
    target.append(textNode(source));
    return;
  }
  const parsed = document.createElement("template");
  parsed.innerHTML = source; // Template content is inert, including resource elements.
  function copy(node, parent, inheritedHighlight = highlight) {
    if (node.nodeType === Node.TEXT_NODE) {
      parent.append(textNode(node.textContent, inheritedHighlight));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || !allowed.has(node.tagName))
      return;
    const child = document.createElement(
      node.tagName === "A" ? "span" : node.tagName.toLowerCase(),
    );
    if (["P", "SPAN"].includes(node.tagName)) {
      for (const key of Array.from(node.style)) {
        if (styles.has(key))
          child.style.setProperty(key, node.style.getPropertyValue(key));
      }
    }
    for (const item of node.childNodes)
      copy(item, child, child.style.backgroundColor || inheritedHighlight);
    parent.append(child);
  }
  for (const node of parsed.content.childNodes) copy(node, target);
}

function placeholder(target, label) {
  const box = document.createElement("div");
  box.className = "placeholder";
  box.textContent = label;
  target.append(box);
}

function fontStyle(target, spec) {
  const family =
    typeof spec.fontFamily === "string"
      ? spec.fontFamily
      : [spec.fontFamily?.latin, spec.fontFamily?.ea].filter(Boolean).join(",");
  Object.assign(target.style, {
    fontFamily: family,
    fontSize: `${spec.fontSize || 16}px`,
    color: color(spec.color, project.deck.theme, "#333333"),
    fontWeight: spec.bold ? "700" : "400",
    fontStyle: spec.italic ? "italic" : "normal",
    lineHeight:
      spec.lineHeightPx !== undefined
        ? `${spec.lineHeightPx}px`
        : String(spec.lineHeight || 1.2),
  });
}

function drawTable(data) {
  const root = document.createElement("div");
  root.className = "table-preview";
  const sum = (values) => values.reduce((a, b) => a + b, 0);
  for (const cell of data.cells) {
    const box = document.createElement("div");
    box.className = "table-cell";
    const style = cell.style;
    Object.assign(box.style, {
      left: `${sum(data.widths.slice(0, cell.column)) * 100}%`,
      top: `${sum(data.heights.slice(0, cell.row)) * 100}%`,
      width: `${sum(data.widths.slice(cell.column, cell.column + cell.colSpan)) * 100}%`,
      height: `${sum(data.heights.slice(cell.row, cell.row + cell.rowSpan)) * 100}%`,
      justifyContent: {
        top: "flex-start",
        middle: "center",
        bottom: "flex-end",
      }[style.align?.[1] || "middle"],
      textAlign: style.align?.[0] || "center",
    });
    paint(box, style.fill);
    fontStyle(box, style);
    if (style.fill?.type === "image")
      imageURL(style.fill.src)
        .then((url) => {
          box.style.backgroundImage = `url("${url}")`;
          box.style.backgroundSize =
            { contain: "contain", fill: "100% 100%", cover: "cover" }[
              style.fill.fit?.mode
            ] || "cover";
          box.style.backgroundPosition = "center";
          box.style.backgroundRepeat = "no-repeat";
        })
        .catch(() => {
          box.dataset.previewError = "图片填充无法预览";
        });
    const sides = Array.isArray(style.border)
      ? style.border.length === 2
        ? [...style.border, ...style.border]
        : style.border
      : Array(4).fill(style.border);
    ["Top", "Right", "Bottom", "Left"].forEach((side, i) => {
      const spec = sides[i];
      if (!spec) return;
      box.style[`border${side}`] =
        `${spec.width ?? 1}px ${{ dash: "dashed", dot: "dotted" }[spec.style] || "solid"} ${color(spec.color, project.deck.theme, "#000000")}`;
    });
    const content = document.createElement("div");
    content.className = "table-text";
    richText(String(cell.text), content);
    box.append(content);
    root.append(box);
  }
  return root;
}

function complexPreview(box, data) {
  const handles = [...box.querySelectorAll(".resize-handle")];
  box.replaceChildren();
  try {
    if (!data || data.error) throw new Error(data?.error || "预览不可用");
    box.append(
      data.kind === "chart"
        ? drawChart(data.model, project.deck.theme)
        : drawTable(data),
    );
  } catch (error) {
    placeholder(box, error.message);
    box.dataset.previewError = error.message;
  }
  box.append(...handles);
}

async function imageURL(src) {
  if (!images.has(src))
    images.set(
      src,
      api(`/api/image?path=${encodeURIComponent(src)}`, undefined, true)
        .then((blob) => URL.createObjectURL(blob))
        .catch((error) => {
          images.delete(src);
          throw error;
        }),
    );
  return images.get(src);
}

function drawElement(item, interactive = true) {
  const box = document.createElement("div");
  box.className = "element";
  box.dataset.id = item.elementId;
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `${item.elementType}: ${item.elementId}`);
  const [x, y, width, height] = item.bounds;
  Object.assign(box.style, {
    left: `${x}px`,
    top: `${y}px`,
    width: `${width}px`,
    height: `${height}px`,
    transform: `rotate(${Number(item.rotation || 0)}deg) scale(${item.flip?.[0] ? -1 : 1},${item.flip?.[1] ? -1 : 1})`,
    opacity: String(item.opacity ?? 1),
  });
  if (item.elementType === "text") {
    box.classList.add("text-element");
    const content = document.createElement("div");
    content.className = "content";
    const spec = textStyle(item.content, project.deck.theme);
    const family =
      typeof spec.fontFamily === "string"
        ? spec.fontFamily
        : `${spec.fontFamily?.latin || "Arial"},${spec.fontFamily?.ea || "sans-serif"}`;
    Object.assign(content.style, {
      fontSize: `${Number(spec.fontSize)}px`,
      fontFamily: family,
      color: color(spec.color, project.deck.theme, "#333333"),
      fontWeight: spec.bold ? "700" : "400",
      fontStyle: spec.italic ? "italic" : "normal",
      lineHeight:
        spec.lineHeightPx !== undefined
          ? `${spec.lineHeightPx}px`
          : String(spec.lineHeight || 1.2),
      textAlign:
        spec.align?.[0] === "distributed"
          ? "justify"
          : spec.align?.[0] || "left",
      display: "flex",
      flexDirection: "column",
      justifyContent: {
        top: "flex-start",
        middle: "center",
        bottom: "flex-end",
      }[spec.align?.[1] || "top"],
    });
    const runs = document.createElement("div");
    runs.style.width = "100%";
    richText(
      String(spec.text ?? ""),
      runs,
      color(spec.backgroundColor, project.deck.theme),
    );
    // Prepare stable, safe text nodes before a mouse gesture starts. Replacing
    // them on pointerdown would invalidate the browser's native caret target.
    if (interactive && !String(spec.text ?? "").includes("\\(")) {
      try {
        runs.innerHTML = writeParagraphs(
          readParagraphs(String(spec.text ?? "")),
          {
            inheritedHighlight: color(spec.backgroundColor, project.deck.theme),
          },
        );
        runs.dataset.editable = "true";
      } catch {
        /* Unsupported markup retains its read-only preview. */
      }
    }
    content.append(runs);
    box.append(content);
  } else if (item.elementType === "shape") {
    try {
      box.append(drawShape(item, (value) => color(value, project.deck.theme)));
    } catch (error) {
      placeholder(box, error.message);
    }
  } else if (item.elementType === "image") {
    const image = document.createElement("img");
    image.alt = item.src;
    image.style.objectFit =
      { fill: "fill", contain: "contain", cover: "cover" }[item.fit?.mode] ||
      "cover";
    box.append(image);
    image.onerror = () => {
      image.remove();
      placeholder(box, "图片无法解码");
    };
    imageURL(item.src)
      .then((url) => {
        image.src = url;
      })
      .catch(() => {
        image.remove();
        placeholder(box, "图片不可预览");
      });
  } else if (item.elementType === "line") {
    try {
      box.append(drawLine(item, (value) => color(value, project.deck.theme)));
    } catch (error) {
      placeholder(box, error.message);
    }
  } else if (["chart", "table"].includes(item.elementType))
    placeholder(box, "正在生成预览…");
  else placeholder(box, `${item.elementType}：待预览`);
  if (interactive) {
    if (item.elementType === "text") {
      for (const edge of ["top", "right", "bottom", "left"]) {
        const strip = document.createElement("div");
        strip.className = `text-move-edge ${edge}`;
        strip.setAttribute("aria-hidden", "true");
        box.append(strip);
      }
    }
    for (const edge of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
      const handle = document.createElement("div");
      handle.className = `resize-handle ${edge}`;
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("pointerdown", (event) =>
        beginResize(event, box, item, edge),
      );
      box.append(handle);
    }
    const rotate = document.createElement("button");
    rotate.className = "rotation-handle";
    rotate.setAttribute("aria-label", "旋转元素");
    rotate.textContent = "↻";
    rotate.addEventListener("pointerdown", (event) =>
      beginRotate(event, box, item),
    );
    box.append(rotate);
    box.addEventListener("pointerdown", (event) => beginDrag(event, box, item));
    if (item.elementType === "text")
      box.addEventListener("dblclick", (event) => {
        if (
          !event.target.closest(
            ".resize-handle,.rotation-handle,.text-move-edge",
          )
        )
          beginTextEdit(box, item);
      });
  }
  return box;
}

function fit() {
  if (!project) return;
  const rect = $("viewport").getBoundingClientRect(),
    [w, h] = project.deck.size,
    style = getComputedStyle($("viewport"));
  scale = canvasScale(
    [w, h],
    [
      rect.width -
        parseFloat(style.paddingLeft) -
        parseFloat(style.paddingRight),
      rect.height -
        parseFloat(style.paddingTop) -
        parseFloat(style.paddingBottom),
    ],
    zoom,
  );
  $("stage-holder").style.width = `${w * scale}px`;
  $("stage-holder").style.height = `${h * scale}px`;
  $("stage").style.transform = `scale(${scale})`;
  $("stage").style.setProperty("--canvas-scale", scale);
  $("zoom-value").textContent = `${Math.round(scale * 100)}%`;
  document
    .querySelector(".workspace")
    .style.setProperty(
      "--notes-height",
      `${$("notes-panel").getBoundingClientRect().height}px`,
    );
}

function select(id, additive = false, retain = false) {
  if (!retain) {
    if (additive && id) {
      if (selectedIds.has(id)) selectedIds.delete(id);
      else selectedIds.add(id);
    } else selectedIds = new Set(id ? [id] : []);
  }
  selected = selectedIds.has(id) ? id : [...selectedIds].at(-1) || null;
  document
    .querySelectorAll("#stage .element")
    .forEach((box) =>
      box.classList.toggle("selected", selectedIds.has(box.dataset.id)),
    );
  document
    .querySelectorAll("#layers button")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.id === id),
    );
  inspect();
  refreshControls();
  if (["chart", "table"].includes(element()?.elementType)) {
    $("theme-panel").hidden = true;
    $("element-panel").hidden = false;
    openInspector(true);
    $("data-panel").open = true;
  }
}

function inspect() {
  const item = element();
  $("selection-label").textContent = item
    ? `${item.elementId} · ${item.elementType}`
    : "请选择元素";
  for (const [i, id] of ["x", "y", "width", "height"].entries())
    $(id).value = item?.bounds[i] ?? "";
  $("rotation").value = item?.rotation ?? 0;
  $("font-size").disabled = item?.elementType !== "text";
  $("font-size").value =
    item?.elementType === "text"
      ? textStyle(item.content, project.deck.theme).fontSize
      : "";
  $("text-label").hidden = item?.elementType !== "text";
  $("text-tools").hidden = item?.elementType !== "text" || selectedIds.size > 1;
  $("shape-tools").hidden =
    !["shape", "line", "image"].includes(item?.elementType) ||
    selectedIds.size > 1;
  if (item) {
    $("shape-fill").value = color(
      item.fill?.color,
      project.deck.theme,
      "#2563EB",
    ).slice(0, 7);
    $("shape-border").replaceChildren(
      document.createTextNode(item.border ? "边框" : "无边框"),
      icon("Down_b"),
    );
    $("shape-border").lastElementChild.classList.add("icon-caret");
    $("shape-replace").disabled = item.elementType !== "shape";
  }
  $("text-details").hidden = item?.elementType !== "text";
  if (item?.elementType === "text") inspectText(item);
  $("text").value = item?.content?.text ?? "";
  $("fill-label").hidden = item?.elementType !== "shape";
  $("fill").value = color(
    item?.fill?.color,
    project.deck.theme,
    "#2563EB",
  ).slice(0, 7);
  inspectData(item);
}

function inspectText(item) {
  const spec = textStyle(item.content, project.deck.theme),
    family = spec.fontFamily;
  $("font-family").value =
    typeof family === "string" ? family : family?.latin || "MiSans";
  $("text-color").value = color(
    spec.color,
    project.deck.theme,
    "#333333",
  ).slice(0, 7);
  $("text-highlight").value = color(
    spec.backgroundColor,
    project.deck.theme,
    "#FFFF00",
  ).slice(0, 7);
  $("text-color").nextElementSibling.style.setProperty(
    "--icon-color",
    $("text-color").value,
  );
  const highlight = color(spec.backgroundColor, project.deck.theme);
  $("text-highlight").nextElementSibling.style.setProperty(
    "--icon-highlight",
    highlight === "transparent" || highlight.endsWith("00")
      ? "transparent"
      : highlight,
  );
  $("text-style").value = item.content.style || "";
  $("text-align").value = spec.align?.[0] || "left";
  $("text-anchor").value = spec.align?.[1] || "top";
  setButtonIcon(
    "text-horizontal",
    {
      left: "LeftAlign",
      center: "CenterAlign",
      right: "RightAlign",
      justify: "Justify",
      distributed: "Justify",
    }[spec.align?.[0]] || "LeftAlign",
    true,
  );
  setButtonIcon(
    "text-vertical",
    {
      top: "TopAlign",
      middle: "CenterVertically",
      bottom: "BottomAlign",
    }[spec.align?.[1]] || "TopAlign",
    true,
  );
  for (const key of ["bold", "italic", "underline", "strike"]) {
    $(`text-${key}`).setAttribute(
      "aria-pressed",
      String(Boolean(spec[key]) || decoration(spec.text, key)),
    );
  }
}

function inspectData(item) {
  const panel = $("data-panel"),
    body = $("data-cells");
  body.replaceChildren();
  panel.hidden = !["chart", "table"].includes(item?.elementType);
  if (panel.hidden) return;
  const id = item.elementId;
  const table = item.elementType === "table",
    data = previews[id];
  if (table && (!data || data.error)) {
    body.textContent = data?.error || "预览尚未就绪";
    return;
  }
  const rows = table ? data.cells.map((cell) => [cell]) : item.data?.rows || [];
  if (rows.length > 80 || (!table && item.data.cols.length > 12)) {
    body.textContent =
      "数据量较大，请在本页 YAML 中编辑；画布和导出保留全部数据。";
    return;
  }
  rows.forEach((row, r) =>
    row.forEach((value, c) => {
      const label = document.createElement("label"),
        input = document.createElement("input");
      label.textContent = table
        ? `第 ${value.row + 1} 行，第 ${value.column + 1} 列`
        : `第 ${r + 1} 行 · ${item.data.cols[c]}`;
      input.value = table ? value.text : (value ?? "");
      input.type = "text";
      input.setAttribute("aria-label", label.textContent);
      input.disabled = busy;
      input.addEventListener("input", markPendingControl);
      input.addEventListener("change", () => {
        const text = input.value;
        action(() =>
          edit((draft) => {
            const target = draft.elements.find((e) => e.elementId === id);
            if (table) target.rows[value.row][value.sourceIndex].text = text;
            else target.data.rows[r][c] = text === "" ? null : text;
          }),
        );
      });
      label.append(input);
      body.append(label);
    }),
  );
}

function previewFor(record) {
  // Reuse the same bounded data normalization for canvas and visible thumbnails.
  const key = record.text;
  if (!previewCache.has(key)) {
    const pending = api("/api/preview", {
      page: record.page,
      theme: project.deck.theme || {},
    });
    previewCache.set(key, pending);
    pending.catch(() => {
      if (previewCache.get(key) === pending) previewCache.delete(key);
    });
    if (previewCache.size > 50)
      previewCache.delete(previewCache.keys().next().value);
  }
  return previewCache.get(key);
}

async function drawThumbnail(button, record, version) {
  if (!button.isConnected || version !== renderVersion) return;
  const frame = button.querySelector(".thumbnail"),
    slide = document.createElement("div");
  slide.className = "slide-preview";
  slide.setAttribute("aria-hidden", "true");
  const [w, h] = project.deck.size,
    factor = frame.clientWidth / w;
  Object.assign(slide.style, {
    width: `${w}px`,
    height: `${h}px`,
    transform: `scale(${factor})`,
  });
  frame.style.height = `${(frame.clientWidth * h) / w}px`;
  paint(slide, record.page.background || { type: "solid", color: "#FFFFFF" });
  // Large pages keep a clearly marked outline thumbnail instead of constructing
  // thousands of hidden DOM elements. The main canvas retains all elements.
  if (record.page.elements.length > 200) {
    frame.textContent = `${record.page.elements.length} 个元素 · 缩略图简化`;
    return;
  }
  for (const item of record.page.elements)
    slide.append(drawElement(item, false));
  frame.replaceChildren(slide);
  if (
    !record.page.elements.some((e) =>
      ["chart", "table"].includes(e.elementType),
    )
  )
    return;
  try {
    const result = await previewFor(record);
    if (!button.isConnected || version !== renderVersion) return;
    for (const box of slide.children)
      if (result.elements[box.dataset.id])
        complexPreview(box, result.elements[box.dataset.id]);
  } catch {
    frame.setAttribute("title", "部分内容无法生成缩略图，请查看画布提示。");
  }
}

function runThumbnails() {
  while (thumbnailWorkers < 2 && thumbnailQueue.length) {
    const args = thumbnailQueue.shift();
    thumbnailWorkers++;
    drawThumbnail(...args)
      .catch(showError)
      .finally(() => {
        thumbnailWorkers--;
        runThumbnails();
      });
  }
}

function render() {
  if (!project) return;
  const draft = page();
  pendingControls = false;
  const version = ++renderVersion;
  thumbnailObserver?.disconnect();
  thumbnailQueue.length = 0;
  thumbnailObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries)
        if (entry.isIntersecting) {
          thumbnailObserver.unobserve(entry.target);
          thumbnailQueue.push([
            entry.target,
            drafts[Number(entry.target.dataset.page)],
            version,
          ]);
        }
      runThumbnails();
    },
    { root: document.querySelector(".pages"), rootMargin: "120px" },
  );
  previews = {};
  selectedIds = new Set(
    [...selectedIds].filter((id) =>
      draft.page.elements.some((item) => item.elementId === id),
    ),
  );
  if (element() && selected) selectedIds.add(selected);
  if (!element()) selected = [...selectedIds].at(-1) || null;
  $("pages").replaceChildren();
  drafts.forEach((record, index) => {
    const button = document.createElement("button");
    button.dataset.page = index;
    button.draggable = true;
    button.addEventListener("dragstart", (event) =>
      event.dataTransfer.setData("application/x-pptd-page", String(index)),
    );
    button.addEventListener("dragover", (event) => {
      if ([...event.dataTransfer.types].includes("application/x-pptd-page"))
        event.preventDefault();
    });
    button.addEventListener("drop", (event) => {
      event.preventDefault();
      const from = Number(
        event.dataTransfer.getData("application/x-pptd-page"),
      );
      if (
        !Number.isInteger(from) ||
        from < 0 ||
        from >= drafts.length ||
        from === index
      )
        return;
      action(async () => {
        await applySource();
        const paths = drafts.map((d) => d.path),
          [path] = paths.splice(from, 1);
        paths.splice(index, 0, path);
        await arrangePages(paths, index);
      });
    });
    button.setAttribute(
      "aria-label",
      `第 ${index + 1} 页 ${record.path.split("/").at(-1)}${record.dirty ? " 未保存" : ""}`,
    );
    button.setAttribute("aria-current", index === current ? "page" : "false");
    const thumb = document.createElement("div");
    thumb.className = "thumbnail";
    thumb.textContent = "正在生成缩略图…";
    const label = document.createElement("span");
    label.className = "page-name";
    label.textContent = `${String(index + 1).padStart(2, "0")}${record.dirty ? " ●" : ""}`;
    button.append(thumb, label);
    button.classList.toggle("active", index === current);
    button.classList.toggle("multi-page", pageSelection.has(index));
    button.addEventListener("click", () =>
      action(async () => {
        await applySource();
        current = index;
        selected = null;
        selectedIds.clear();
        pageSelection = new Set([index]);
        render();
      }),
    );
    $("pages").append(button);
    thumbnailObserver.observe(button);
  });
  $("layers").replaceChildren();
  for (const item of [...draft.page.elements].reverse()) {
    const button = document.createElement("button");
    button.textContent = `${item.elementType} · ${item.elementId}`;
    button.dataset.id = item.elementId;
    button.addEventListener("click", () => {
      if (!busy) select(item.elementId);
    });
    $("layers").append(button);
  }
  const stage = $("stage");
  stage.replaceChildren();
  stage.style.width = `${project.deck.size[0]}px`;
  stage.style.height = `${project.deck.size[1]}px`;
  paint(stage, draft.page.background || { type: "solid", color: "#FFFFFF" });
  for (const item of draft.page.elements) stage.append(drawElement(item));
  $("source").value = draft.text;
  $("notes").value = draft.page.notes ?? "";
  $("page-label").textContent = `${current + 1} / ${drafts.length}`;
  $("warnings").replaceChildren();
  for (const message of previewWarnings(draft.page, project.deck)) {
    const li = document.createElement("li");
    li.textContent = message;
    $("warnings").append(li);
  }
  status(
    drafts.some((item) => item.dirty) || themeDirty()
      ? "存在未保存草稿"
      : "全部页面已保存",
  );
  select(selected, false, true);
  fit();
  const complex = draft.page.elements.filter((e) =>
    ["chart", "table"].includes(e.elementType),
  );
  if (complex.length)
    previewFor(draft)
      .then((result) => {
        if (version !== renderVersion) return;
        previews = result.elements;
        for (const box of stage.children)
          if (previews[box.dataset.id])
            complexPreview(box, previews[box.dataset.id]);
        inspectData(element());
      })
      .catch((error) => {
        if (version !== renderVersion) return;
        for (const box of stage.children)
          if (complex.some((e) => e.elementId === box.dataset.id))
            complexPreview(box, { error: error.message });
      });
}

function beginDrag(event, box, item) {
  if (busy || event.button !== 0) return;
  if (hasPendingSource()) {
    showError(new Error("请先应用 YAML 源码，再操作画布。"));
    return;
  }
  if (
    item.elementType === "text" &&
    selected === item.elementId &&
    selectedIds.size === 1 &&
    !event.shiftKey &&
    event.target.closest('.content>div[data-editable="true"]')
  ) {
    event.stopPropagation();
    beginTextEdit(box, item);
    // Native mouse handling places the caret / selects words and drags ranges.
    return;
  }
  const textEdit = detachTextForGesture();
  event.preventDefault();
  if (event.shiftKey) {
    select(item.elementId, true);
    commitCanvasGesture(textEdit);
    return;
  }
  select(item.elementId, false, selectedIds.has(item.elementId));
  $("stage").focus();
  const start = [event.clientX, event.clientY],
    bounds = [...item.bounds];
  const group = page()
    .page.elements.filter((e) => selectedIds.has(e.elementId))
    .map((e) => [e.elementId, [...e.bounds]]);
  let dx = 0,
    dy = 0,
    moved = false;
  box.setPointerCapture(event.pointerId);
  const move = (e) => {
    if (!moved && Math.hypot(e.clientX - start[0], e.clientY - start[1]) < 4)
      return;
    moved = true;
    dx = Math.round((e.clientX - start[0]) / scale);
    dy = Math.round((e.clientY - start[1]) / scale);
    for (const [identifier, b] of group) {
      const target = [...$("stage").children].find(
        (e) => e.dataset.id === identifier,
      );
      target.style.left = `${b[0] + dx}px`;
      target.style.top = `${b[1] + dy}px`;
    }
  };
  const stop = (e) => {
    box.removeEventListener("pointermove", move);
    box.removeEventListener("pointerup", stop);
    box.removeEventListener("pointercancel", stop);
    if (box.hasPointerCapture(event.pointerId))
      box.releasePointerCapture(event.pointerId);
    if (e.type === "pointercancel") {
      commitCanvasGesture(textEdit, null, true);
      return;
    }
    commitCanvasGesture(
      textEdit,
      dx || dy
        ? (value) => {
            for (const [identifier, b] of group)
              value.elements.find((e) => e.elementId === identifier).bounds = [
                b[0] + dx,
                b[1] + dy,
                b[2],
                b[3],
              ];
          }
        : null,
    );
  };
  box.addEventListener("pointermove", move);
  box.addEventListener("pointerup", stop);
  box.addEventListener("pointercancel", stop);
}

function beginResize(event, box, item, edge) {
  event.stopPropagation();
  if (busy || event.button !== 0) return;
  if (hasPendingSource()) {
    showError(new Error("请先应用源码，再操作画布。"));
    return;
  }
  event.preventDefault();
  const textEdit = detachTextForGesture();
  select(item.elementId);
  const handle = event.currentTarget,
    start = [event.clientX, event.clientY],
    bounds = [...item.bounds];
  let next = bounds;
  handle.setPointerCapture(event.pointerId);
  const move = (e) => {
    next = resizeBounds(
      bounds,
      Number(item.rotation || 0),
      item.flip,
      [(e.clientX - start[0]) / scale, (e.clientY - start[1]) / scale],
      edge,
      e.shiftKey,
    );
    Object.assign(box.style, {
      left: `${next[0]}px`,
      top: `${next[1]}px`,
      width: `${next[2]}px`,
      height: `${next[3]}px`,
    });
  };
  const stop = (e) => {
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", stop);
    handle.removeEventListener("pointercancel", stop);
    if (handle.hasPointerCapture(event.pointerId))
      handle.releasePointerCapture(event.pointerId);
    if (e.type === "pointercancel") {
      commitCanvasGesture(textEdit, null, true);
      return;
    }
    commitCanvasGesture(
      textEdit,
      next.some((n, i) => n !== bounds[i])
        ? (draft) => {
            draft.elements.find((e) => e.elementId === item.elementId).bounds =
              next.map((n) => Math.round(n * 100) / 100);
          }
        : null,
    );
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
}

function openInspector(open) {
  $("inspector").hidden = !open;
  document.body.classList.toggle("inspector-open", open);
  $("toggle-inspector").setAttribute("aria-expanded", String(open));
}
for (const id of ["toggle-inspector", "text-more"])
  $(id).addEventListener("click", () => {
    $("theme-panel").hidden = true;
    $("element-panel").hidden = false;
    openInspector(id === "toggle-inspector" ? $("inspector").hidden : true);
  });
$("close-inspector").addEventListener("click", () => openInspector(false));
$("toggle-pages").addEventListener("click", () => {
  const hidden = !$("page-sidebar").hidden;
  $("page-sidebar").hidden = hidden;
  document.body.classList.toggle("pages-hidden", hidden);
  $("toggle-pages").setAttribute("aria-expanded", String(!hidden));
});

for (const [index, id] of ["x", "y", "width", "height"].entries()) {
  $(id).addEventListener("input", markPendingControl);
  $(id).addEventListener("change", () => {
    const value = Number($(id).value),
      target = selected;
    action(() => {
      if (!Number.isFinite(value) || (index > 1 && value <= 0))
        throw new Error("宽和高必须大于 0，坐标必须是有限数值。");
      return edit((draft) => {
        draft.elements.find((item) => item.elementId === target).bounds[index] =
          value;
      });
    });
  });
}
for (const id of ["rotation", "font-size", "text", "fill"]) {
  $(id).addEventListener("input", markPendingControl);
  $(id).addEventListener("change", () => {
    const value = $(id).value,
      target = selected;
    if (id === "font-size" && applyInlineText({ fontSize: Number(value) }))
      return;
    action(() => {
      return edit((draft) => {
        const item = draft.elements.find((entry) => entry.elementId === target);
        if (id === "rotation") item.rotation = Number(value);
        if (id === "font-size")
          formatText(item.content, "fontSize", Number(value));
        if (id === "text") item.content.text = value;
        if (id === "fill") item.fill = { type: "solid", color: value };
      });
    });
  });
}
for (const id of ["font-family", "text-color", "text-highlight"]) {
  $(id).addEventListener("input", markPendingControl);
  $(id).addEventListener("change", () => {
    const value = $(id).value,
      target = selected;
    if (
      applyInlineText({
        [id.startsWith("font-")
          ? "fontFamily"
          : id === "text-color"
            ? "color"
            : "backgroundColor"]: value,
      })
    )
      return;
    action(() =>
      edit((draft) => {
        const content = draft.elements.find(
          (e) => e.elementId === target,
        ).content;
        if (id.startsWith("font-")) {
          if (!value.trim()) throw new Error("字体名称不能为空。");
          formatText(content, "fontFamily", value.trim());
        } else {
          if (id === "text-color") delete content.gradient;
          formatText(
            content,
            id === "text-color" ? "color" : "backgroundColor",
            value,
          );
        }
      }),
    );
  });
}
for (const key of ["bold", "italic", "underline", "strike"])
  $(`text-${key}`).addEventListener("click", () => {
    const target = selected,
      value = $(`text-${key}`).getAttribute("aria-pressed") !== "true";
    if (applyInlineText({ [key]: value })) return;
    action(() =>
      edit((draft) =>
        formatText(
          draft.elements.find((e) => e.elementId === target).content,
          key,
          value,
        ),
      ),
    );
  });
$("clear-highlight").addEventListener("click", () => {
  if (applyInlineText({ backgroundColor: "#00000000" })) return;
  const target = selected;
  action(() =>
    edit((draft) => {
      const content = draft.elements.find(
        (e) => e.elementId === target,
      ).content;
      // Explicit transparent overrides a theme's inherited highlight.
      formatText(content, "backgroundColor", "#00000000");
    }),
  );
});
for (const id of ["text-align", "text-anchor"])
  $(id).addEventListener("change", () => {
    const target = selected,
      value = $(id).value;
    action(() =>
      edit((draft) => {
        const content = draft.elements.find(
          (e) => e.elementId === target,
        ).content;
        const align = [...(content.align || ["left", "top"])];
        align[id === "text-align" ? 0 : 1] = value;
        formatText(content, "align", align);
      }),
    );
  });
$("text-style").addEventListener("change", () => {
  const target = selected,
    value = $("text-style").value;
  action(() =>
    edit((draft) => {
      const content = draft.elements.find(
        (e) => e.elementId === target,
      ).content;
      if (!value) {
        delete content.style;
        return;
      }
      const themeStyle = project.deck.theme.textStyles[value.slice(1)];
      for (const [key, entry] of Object.entries(themeStyle))
        formatText(content, key, entry);
      // The chosen style remains a reference so future theme changes can apply.
      for (const key of Object.keys(themeStyle)) delete content[key];
      content.style = value;
    }),
  );
});
$("notes").addEventListener("input", markPendingControl);
$("notes").addEventListener("change", () => {
  const text = $("notes").value;
  action(() =>
    edit((draft) => {
      draft.notes = text;
    }),
  );
});
$("toggle-notes").addEventListener("click", () => {
  $("notes-panel").hidden = !$("notes-panel").hidden;
  $("toggle-notes").setAttribute(
    "aria-expanded",
    String(!$("notes-panel").hidden),
  );
  $("toggle-notes").textContent = $("notes-panel").hidden
    ? "显示演讲者备注"
    : "隐藏演讲者备注";
});
function setZoom(value) {
  zoom = value;
  let option = $("zoom").querySelector("[data-custom]");
  option?.remove();
  const choice = value === null ? "fit" : String(value);
  if (!Array.from($("zoom").options).some((item) => item.value === choice)) {
    option = document.createElement("option");
    option.dataset.custom = "true";
    option.value = choice;
    option.textContent = `${Math.round(value * 100)}%`;
    $("zoom").append(option);
  }
  $("zoom").value = choice;
  fit();
}
$("zoom").addEventListener("change", () =>
  setZoom($("zoom").value === "fit" ? null : Number($("zoom").value)),
);
for (const [id, step] of [
  ["zoom-in", 0.1],
  ["zoom-out", -0.1],
])
  $(id).addEventListener("click", () => {
    setZoom(Math.max(0.1, Math.min(4, Math.round((scale + step) * 100) / 100)));
  });
for (const [id, direction] of [
  ["layer-up", 1],
  ["layer-down", -1],
])
  $(id).addEventListener("click", () => {
    const target = selected;
    action(() => edit((draft) => moveLayer(draft, target, direction)));
  });
$("source").addEventListener("input", () => {
  status("源码尚未应用");
  refreshControls();
});
$("apply-source").addEventListener("click", () =>
  action(async () => {
    await applySource();
    render();
  }),
);
$("save").addEventListener("click", () =>
  action(async () => {
    if (pendingControls)
      throw new Error("属性输入尚未成功提交，请修正输入并离开输入框后再保存。");
    await applySource();
    const draft = page(),
      text = draft.text;
    const result = await api("/api/save", {
      path: draft.path,
      text,
      hash: draft.hash,
      manifestHash: project.manifestHash,
    });
    draft.saved(result.hash, text);
    await saveTheme();
    render();
    status("本页与主题已保存到项目文件");
  }),
);
function exportSettings(resetName = false) {
  const format = $("export-format").value;
  const folder = $("export-destination").value === "folder";
  $("export-directory-row").hidden = !folder;
  $("export-download").textContent = folder ? "保存" : "下载";
  $("export-transition").disabled = format !== "pptx";
  $("export-scope").textContent =
    format === "pptx"
      ? "PPT 包含全部页面及未保存草稿。"
      : format === "png"
        ? "PNG 导出当前页，包含当前使用的字体外观。"
        : "SVG 导出当前页，字体外观依赖接收电脑的字体。";
  if (resetName || !$("export-filename").value)
    $("export-filename").value =
      format === "pptx"
        ? project.manifest
            .split("/")
            .at(-1)
            .replace(/\.pptd$/i, ".pptx")
        : `slide-${current + 1}.${format}`;
  controls.sync();
}
$("export").addEventListener("click", () => {
  exportSettings();
  $("export-dialog").showModal();
});
$("export-format").addEventListener("change", () => exportSettings(true));
$("export-destination").addEventListener("change", () => exportSettings());
$("export-download").addEventListener("click", () =>
  action(async () => {
    if (pendingControls) throw new Error("请先提交属性输入。");
    const format = $("export-format").value;
    const filename = $("export-filename").value.trim();
    const folder = $("export-destination").value === "folder";
    const directory = $("export-directory").value.trim();
    if (
      !filename ||
      /[\\/:\x00-\x1f]/.test(filename) ||
      !filename.toLowerCase().endsWith(`.${format}`)
    )
      throw new Error(`请输入以 .${format} 结尾的文件名，不要包含路径。`);
    if (folder && !directory) throw new Error("请填写保存文件夹的绝对路径。");
    await applySource();
    let blob;
    if (format !== "pptx") {
      const svg = await slideImage(page());
      blob = format === "png" ? await rasterImage(svg, project.deck.size) : svg;
    } else {
      status("正在生成 PPTX…");
      blob = await api(
        "/api/export",
        {
          ...exportSnapshot(),
          transition: $("export-transition").value,
          embedFonts: false,
        },
        true,
      );
    }
    let saved;
    if (folder) {
      if (blob.size > 20 * 1024 * 1024)
        throw new Error("导出文件超过 20 MiB，请使用浏览器下载。");
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(new Error("读取导出文件失败。"));
        reader.readAsDataURL(blob);
      });
      saved = await api("/api/save-export", { data, directory, filename });
    } else download(blob, filename);
    $("export-dialog").close();
    render();
    status(saved ? `已保存：${saved.path}` : "已交给浏览器下载");
  }),
);
$("download-draft").addEventListener("click", () =>
  action(async () =>
    download(
      new Blob([$("source").value], { type: "text/yaml" }),
      page().path.split("/").at(-1),
    ),
  ),
);
for (const command of ["undo", "redo"])
  $(command).addEventListener("click", () => {
    if (textSession) {
      textSession.travel(command);
      return;
    }
    return action(async () => {
      await applySource();
      if (!$("theme-panel").hidden && !$("inspector").hidden) {
        const from = command === "undo" ? themeUndo : themeRedo,
          to = command === "undo" ? themeRedo : themeUndo;
        if (from.length) {
          to.push(clone(project.deck.theme || {}));
          project.deck.theme = from.pop();
          previewCache.clear();
          syncThemeStyles();
          renderTheme();
        }
      } else await travelHistory(command);
      render();
    });
  });
for (const kind of ["text", "table", "chart"])
  $(`add-${kind}`).addEventListener("click", () =>
    action(() =>
      edit((value) => {
        const item = newElement(value, kind);
        value.elements.push(item);
        selected = item.elementId;
      }),
    ),
  );
$("add-image").addEventListener("click", () => {
  $("image-file").value = "";
  $("image-file").click();
});
$("image-file").addEventListener("change", () => {
  const file = $("image-file").files[0];
  if (!file) return;
  action(async () => {
    if (file.size > 10 * 1024 * 1024)
      throw new Error("图片必须小于 10 MiB；当前支持 PNG/JPEG。");
    await applySource();
    const encoded = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("读取图片失败。"));
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.readAsDataURL(file);
    });
    const asset = await api("/api/import-image", { data: encoded });
    await edit((value) => {
      const item = newElement(value, "image"),
        ratio = Math.min(
          1,
          (project.deck.size[0] * 0.6) / asset.width,
          (project.deck.size[1] * 0.6) / asset.height,
        );
      item.src = asset.path;
      item.bounds = [40, 40, asset.width * ratio, asset.height * ratio];
      value.elements.push(item);
      selected = item.elementId;
    });
    status("图片资源已导入；元素仍是草稿，可撤销或保存本页。");
  });
});
$("duplicate").addEventListener("click", () =>
  action(() =>
    edit((value) => {
      const source = value.elements.find((item) => item.elementId === selected),
        item = clone(source);
      let suffix = 1;
      while (
        value.elements.some(
          (entry) => entry.elementId === `${source.elementId}-copy-${suffix}`,
        )
      )
        suffix++;
      item.elementId = `${source.elementId}-copy-${suffix}`;
      item.bounds[0] += 20;
      item.bounds[1] += 20;
      value.elements.push(item);
      selected = item.elementId;
    }),
  ),
);
function removeSelected() {
  const targets = [...selectedIds];
  if (!targets.length) return;
  return action(() =>
    edit((value) => {
      for (const id of targets) deleteElement(value, id);
      selected = null;
      selectedIds.clear();
    }),
  );
}
for (const id of ["delete", "delete-selection"])
  $(id).addEventListener("click", removeSelected);
$("stage").addEventListener("pointerdown", (event) => {
  if (event.target === $("stage")) select(null);
});
$("stage").addEventListener("keydown", (event) => {
  if (
    element()?.elementType === "text" &&
    ["Enter", "F2"].includes(event.key)
  ) {
    event.preventDefault();
    const box = [...$("stage").children].find(
      (node) => node.dataset.id === selected,
    );
    if (box) beginTextEdit(box, element());
    return;
  }
  const deltas = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
  };
  if (!element() || !deltas[event.key]) return;
  event.preventDefault();
  const [x, y] = deltas[event.key],
    step = event.shiftKey ? 10 : 1;
  action(() =>
    edit((value) => {
      const item = value.elements.find((e) => e.elementId === selected);
      item.bounds[0] += x * step;
      item.bounds[1] += y * step;
    }),
  );
});
document.addEventListener("keydown", (event) => {
  const editing = event.target.closest?.("input,textarea,[contenteditable]");
  if (
    !editing &&
    !$("presentation").open &&
    ["Delete", "Backspace"].includes(event.key) &&
    element()
  ) {
    event.preventDefault();
    removeSelected();
    return;
  }
  if (event.key === "F5" && !$("presentation").open) {
    event.preventDefault();
    startPresentation(event.shiftKey ? current : 0);
    return;
  }
  if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
  const key = event.key.toLowerCase(),
    input = event.target.closest?.("input,textarea,[contenteditable]");
  // Text fields retain their platform text undo. Canvas undo is per page.
  const command =
    key === "s"
      ? "save"
      : !input && key === "z"
        ? event.shiftKey
          ? "redo"
          : "undo"
        : !input && key === "y"
          ? "redo"
          : null;
  if (!command) return;
  event.preventDefault();
  if (command === "save") document.activeElement?.blur();
  $(command).click();
});
window.addEventListener("beforeunload", (event) => {
  if (
    drafts.some((draft) => draft.dirty) ||
    themeDirty() ||
    hasPendingSource() ||
    pendingControls ||
    textSession?.dirty
  ) {
    event.preventDefault();
    event.returnValue = "";
  }
});
new ResizeObserver(fit).observe($("viewport"));
new ResizeObserver(() => {
  const [w, h] = project?.deck.size || [1, 1];
  for (const frame of document.querySelectorAll(".thumbnail")) {
    const slide = frame.querySelector(".slide-preview");
    if (!slide) continue;
    frame.style.height = `${(frame.clientWidth * h) / w}px`;
    slide.style.transform = `scale(${frame.clientWidth / w})`;
  }
}).observe($("page-sidebar"));

function formulaExpression(source) {
  if (!formulaCache.has(source)) {
    const promise = api("/api/formula", { source });
    formulaCache.set(source, promise);
    promise.catch(() => formulaCache.delete(source));
    if (formulaCache.size > 300)
      formulaCache.delete(formulaCache.keys().next().value);
  }
  return formulaCache.get(source);
}
function formulaText(text, highlight) {
  const result = document.createDocumentFragment();
  const appendText = (value) => {
    if (!value) return;
    if (!highlight || highlight === "transparent") {
      result.append(document.createTextNode(value));
      return;
    }
    const span = document.createElement("span");
    span.style.backgroundColor = highlight;
    span.textContent = value;
    result.append(span);
  };
  let offset = 0;
  for (const match of text.matchAll(/\\\(([\s\S]*?)\\\)/g)) {
    appendText(text.slice(offset, match.index));
    const span = document.createElement("span");
    span.textContent = match[0];
    span.style.backgroundColor = highlight || "transparent";
    formulaExpression(match[1])
      .then(({ expression }) => span.replaceChildren(drawMath(expression)))
      .catch((error) => {
        span.title = error.message;
        span.className = "formula-invalid";
      });
    result.append(span);
    offset = match.index + match[0].length;
  }
  appendText(text.slice(offset));
  return result;
}
function closeMenus() {
  $("shape-menu").hidden = $("more-menu").hidden = true;
  $("add-shape").setAttribute("aria-expanded", "false");
  $("more-insert").setAttribute("aria-expanded", "false");
}
function shapeChoices(kind = "shape") {
  $("shape-options").replaceChildren();
  for (const [id, active] of [
    ["shape-tab", kind === "shape"],
    ["line-tab", kind === "line"],
    ["icon-tab", kind === "icon"],
  ])
    $(id).setAttribute("aria-selected", String(active));
  const options =
    kind === "shape"
      ? SHAPES
      : kind === "line"
        ? [
            ["line", "直线", "线条"],
            ["arrow", "单向箭头", "线条"],
            ["double", "双向箭头", "线条"],
            ["dash", "虚线", "线条"],
            ["dot", "点线", "线条"],
          ]
        : [
            ["check", "确认", "自绘图标"],
            ["home", "主页", "自绘图标"],
            ["heart", "爱心", "自绘图标"],
            ["search", "搜索", "自绘图标"],
            ["person", "人物", "自绘图标"],
            ["clock", "时钟", "自绘图标"],
            ["info", "信息", "自绘图标"],
            ["mail", "邮件", "自绘图标"],
          ];
  let category = "";
  for (const [name, label, group] of options) {
    if (group !== category) {
      category = group;
      const heading = document.createElement("h4");
      heading.textContent = group;
      $("shape-options").append(heading);
    }
    const button = document.createElement("button");
    button.setAttribute("aria-label", `插入${label}`);
    button.title = label;
    if (kind === "shape")
      button.append(
        drawShape(
          {
            shapeName: name,
            fill: { type: "solid", color: "#FFFFFF" },
            border: { color: "#747982", width: 1, style: "solid" },
          },
          (value) => value,
        ),
      );
    else if (kind === "line")
      button.textContent = {
        line: "—",
        arrow: "⟶",
        double: "⟷",
        dash: "┄",
        dot: "┈",
      }[name];
    else button.append(iconSVG(name));
    button.addEventListener("click", () => {
      closeMenus();
      action(async () => {
        if (kind === "icon") {
          await insertIcon(name);
          return;
        }
        await edit((value) => {
          const item = newElement(value, kind);
          if (kind === "shape") {
            if (replacingShape) {
              value.elements.find((e) => e.elementId === selected).shapeName =
                name;
              replacingShape = false;
              return;
            }
            item.shapeName = name;
            item.bounds = [80, 80, 180, 140];
          } else {
            item.arrow =
              name === "double"
                ? ["arrow", "arrow"]
                : name === "arrow"
                  ? [null, "arrow"]
                  : [null, null];
            item.border.style = ["dash", "dot"].includes(name) ? name : "solid";
          }
          value.elements.push(item);
          selected = item.elementId;
        });
      });
    });
    $("shape-options").append(button);
  }
}
function iconSVG(name) {
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "96");
  svg.setAttribute("height", "96");
  const paths = {
    check: "M4 12 9 17 20 6",
    home: "M3 11 12 3 21 11M5 10v11h14V10M10 21v-7h4v7",
    heart:
      "M12 20C8 16 3 12 3 8C3 2 10 2 12 7C14 2 21 2 21 8C21 12 16 16 12 20Z",
    search: "M16 16 22 22M19 10a9 9 0 1 1-18 0a9 9 0 1 1 18 0",
    person: "M16 6a4 4 0 1 1-8 0a4 4 0 1 1 8 0M4 22v-2a8 8 0 0 1 16 0v2",
    clock: "M22 12a10 10 0 1 1-20 0a10 10 0 1 1 20 0M12 5v7l5 3",
    info: "M22 12a10 10 0 1 1-20 0a10 10 0 1 1 20 0M12 11v7M12 6v1",
    mail: "M2 4h20v16H2ZM2 4l10 9L22 4",
  };
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", paths[name]);
  for (const [key, value] of Object.entries({
    fill: "none",
    stroke: "#172554",
    "stroke-width": 1.8,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }))
    path.setAttribute(key, value);
  svg.append(path);
  return svg;
}
async function insertIcon(name) {
  const svg = iconSVG(name),
    url = URL.createObjectURL(
      new Blob([new XMLSerializer().serializeToString(svg)], {
        type: "image/svg+xml",
      }),
    );
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 192;
    canvas.getContext("2d").drawImage(image, 0, 0, 192, 192);
    const asset = await api("/api/import-image", {
      data: canvas.toDataURL("image/png").split(",")[1],
    });
    await edit((value) => {
      const item = newElement(value, "image");
      item.src = asset.path;
      item.bounds = [80, 80, 96, 96];
      value.elements.push(item);
      selected = item.elementId;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}
$("add-shape").addEventListener("click", () => {
  const open = $("shape-menu").hidden;
  closeMenus();
  $("shape-menu").hidden = !open;
  $("add-shape").setAttribute("aria-expanded", String(open));
  shapeChoices();
});
for (const [id, kind] of [
  ["shape-tab", "shape"],
  ["line-tab", "line"],
  ["icon-tab", "icon"],
])
  $(id).addEventListener("click", () => shapeChoices(kind));
$("more-insert").addEventListener("click", () => {
  const open = $("more-menu").hidden;
  closeMenus();
  $("more-menu").hidden = !open;
  $("more-insert").setAttribute("aria-expanded", String(open));
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".floating-menu,#add-shape,#more-insert"))
    closeMenus();
});
for (const button of document.querySelectorAll("[data-close]"))
  button.addEventListener("click", () => $(button.dataset.close).close());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenus();
});

let formulaRevision = 0;
let formulaTarget = null;
async function updateFormula() {
  const version = ++formulaRevision;
  formulaValid = false;
  for (const id of ["shape-replace", "shape-fill", "shape-fill-options"])
    $(id).disabled = element()?.elementType !== "shape";
  $("formula-apply").disabled = true;
  $("formula-error").textContent = "";
  try {
    const { expression } = await formulaExpression($("formula-source").value);
    if (version !== formulaRevision) return;
    formulaValid = true;
    $("formula-preview").replaceChildren(drawMath(expression));
    for (const id of ["shape-replace", "shape-fill", "shape-fill-options"])
      $(id).disabled = element()?.elementType !== "shape";
    $("formula-apply").disabled = false;
  } catch (error) {
    if (version === formulaRevision) {
      $("formula-preview").replaceChildren();
      $("formula-error").textContent = error.message;
    }
  }
}
$("insert-formula").addEventListener("click", () => {
  closeMenus();
  formulaTarget = null;
  $("formula-location-row").hidden = true;
  $("formula-title").textContent = "插入独立公式";
  $("formula-apply").textContent = "插入公式";
  $("formula-dialog").showModal();
  updateFormula();
});
const formulaExamples = {
  cos: String.raw`\text{cos} x`,
  kl: String.raw`D_{KL}(P \parallel Q) = \int P(x) \log \frac{P(x)}{Q(x)} dx`,
  normal: String.raw`p(x) = \frac{1}{\sqrt{2 \pi \sigma^2}} \exp \left(-\frac{(x - \mu)^2}{2\sigma^2} \right)`,
  matrix: String.raw`A = \begin{pmatrix}a & b \\ c & d\end{pmatrix}`,
  cases: String.raw`f(x) = \begin{cases}x^2 & x \ge 0 \\ -x & x < 0\end{cases}`,
};
for (const button of document.querySelectorAll("[data-formula-example]")) {
  button.addEventListener("click", () => {
    $("formula-source").value = formulaExamples[button.dataset.formulaExample];
    updateFormula();
  });
}
$("formula-source").addEventListener("input", updateFormula);
$("formula-apply").addEventListener("click", () =>
  action(async () => {
    const source = $("formula-source").value;
    await formulaExpression(source);
    const preview = $("formula-preview").querySelector("math");
    const measured = preview?.getBoundingClientRect();
    const previewSize = parseFloat(getComputedStyle($("formula-preview")).fontSize) || 32;
    const [pageWidth, pageHeight] = project.deck.size;
    const availableWidth = Math.max(40, pageWidth - 160);
    const availableHeight = Math.max(40, pageHeight - 160);
    const scale = measured?.width && measured?.height
      ? Math.min(36 / previewSize, availableWidth / (measured.width + 24), availableHeight / (measured.height + 24))
      : 36 / previewSize;
    const formulaBounds = [Math.min(80, pageWidth / 4), Math.min(80, pageHeight / 4),
      Math.min(availableWidth, Math.max(80, (measured?.width || 200) * scale + 24)),
      Math.min(availableHeight, Math.max(60, (measured?.height || 60) * scale + 24))];
    await edit((value) => {
      if (formulaTarget) {
        const item = value.elements.find(
          (e) => e.elementId === formulaTarget.id,
        );
        if (!item) throw new Error("文字框已移除。");
        const chosen = $("formula-location").value;
        const match =
          chosen === "new" ? null : formulaTarget.matches[Number(chosen)];
        const [start, end] = match
          ? [match.index, match.index + match[0].length]
          : formulaTarget.range;
        item.content.text = writeParagraphs(
          replaceSelection(
            readParagraphs(String(item.content.text ?? "")),
            start,
            end,
            `\\(${source}\\)`,
          ),
        );
        return;
      }
      const item = newElement(value, "text");
      item.content.text = `\\(${source}\\)`;
      item.content.fontSize = Math.round(previewSize * scale * 100) / 100;
      item.bounds = formulaBounds;
      value.elements.push(item);
      selected = item.elementId;
    });
    $("formula-dialog").close();
  }),
);

async function editPages(indices, update) {
  await applySource();
  const changes = [];
  for (const index of indices) {
    const value = clone(drafts[index].page);
    update(value, index);
    const { text } = await api("/api/serialize", { page: value });
    changes.push({ index, value, text });
  }
  const changed = [];
  for (const { index, value, text } of changes)
    if (drafts[index].text !== text) {
      drafts[index].change(text, value);
      changed.push(drafts[index]);
    }
  if (changed.length) recordHistory({ kind: "pages", drafts: changed });
  render();
}
async function imageAsset(file) {
  if (!file || file.size > 10 * 1024 * 1024)
    throw new Error("请选择 10 MiB 以内的 PNG/JPEG 图片。");
  const data = await encodeFile(file);
  return api("/api/import-image", { data });
}
function encodeFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取本地文件失败。"));
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.readAsDataURL(file);
  });
}
let watermarkLogo = null;
function watermarkPreview() {
  const target = $("watermark-preview");
  target.replaceChildren();
  target.style.opacity = "1";
  const opacity = Math.max(
    0,
    Math.min(1, Number($("watermark-opacity").value) / 100),
  );
  if (watermarkLogo) {
    const image = document.createElement("img");
    image.style.maxHeight = "80px";
    image.style.maxWidth = "100%";
    image.style.opacity = String(opacity);
    imageURL(watermarkLogo.path).then((url) => (image.src = url));
    target.append(image);
  } else {
    target.textContent = $("watermark-text").value || "水印预览";
    target.style.color = "#555";
    target.style.opacity = String(opacity);
  }
}
$("insert-watermark").addEventListener("click", () => {
  closeMenus();
  $("watermark-dialog").showModal();
  watermarkPreview();
});
for (const id of ["watermark-text", "watermark-opacity", "watermark-position"])
  $(id).addEventListener("input", watermarkPreview);
$("watermark-file").addEventListener("change", () =>
  action(async () => {
    if (!$("watermark-file").files[0]) return;
    watermarkLogo = await imageAsset($("watermark-file").files[0]);
    watermarkPreview();
  }),
);
for (const [id, all] of [
  ["watermark-current", false],
  ["watermark-all", true],
])
  $(id).addEventListener("click", () =>
    action(async () => {
      const text = $("watermark-text").value.trim(),
        opacity = Number($("watermark-opacity").value) / 100,
        center = $("watermark-position").value === "center";
      if (!watermarkLogo && !text)
        throw new Error("请输入文字水印或上传 Logo。");
      if (!Number.isFinite(opacity) || opacity < 0 || opacity > 1)
        throw new Error("水印不透明度必须在 0–100 之间。");
      const [w, h] = project.deck.size;
      await editPages(all ? drafts.map((_, i) => i) : [current], (value) => {
        const item = newElement(value, watermarkLogo ? "image" : "text");
        let width = Math.min(w * 0.4, center ? 360 : 200),
          height = watermarkLogo
            ? (width * watermarkLogo.height) / watermarkLogo.width
            : Math.min(60, h * 0.3);
        if (height > h * 0.5) {
          width *= (h * 0.5) / height;
          height = h * 0.5;
        }
        item.bounds = [
          center ? (w - width) / 2 : w - width - 24,
          center ? (h - height) / 2 : h - height - 20,
          width,
          height,
        ];
        item.opacity = opacity;
        if (watermarkLogo) item.src = watermarkLogo.path;
        else {
          item.content = {
            text,
            fontSize: center ? 36 : 20,
            fontFamily: "Arial",
            color: "#555555",
            align: ["center", "middle"],
          };
          item.rotation = center ? -25 : 0;
        }
        value.elements.push(item);
      });
      $("watermark-dialog").close();
      status(
        all
          ? "水印已加入所有页面草稿；保存或下载项目以保留。"
          : "水印已加入本页草稿。",
      );
    }),
  );

function changeTheme(update) {
  const value = clone(project.deck.theme || {});
  update(value);
  themeUndo.push(clone(project.deck.theme || {}));
  if (themeUndo.length > 50) themeUndo.shift();
  themeRedo = [];
  project.deck.theme = value;
  previewCache.clear();
  syncThemeStyles();
  renderTheme();
  render();
}
function syncThemeStyles() {
  $("text-style").replaceChildren();
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "未应用";
  $("text-style").append(none);
  for (const name of Object.keys(project.deck.theme?.textStyles || {})) {
    const option = document.createElement("option");
    option.value = "$" + name;
    option.textContent = name;
    $("text-style").append(option);
  }
}
function renderTheme() {
  const theme = project.deck.theme || {};
  $("theme-source").value = JSON.stringify(theme, null, 2);
  $("theme-colors").replaceChildren();
  $("theme-styles").replaceChildren();
  for (const [name, value] of Object.entries(theme.colors || {})) {
    const label = document.createElement("div");
    label.className = "theme-color-row";
    label.append(document.createTextNode(name));
    const input = document.createElement("input");
    input.type = "color";
    input.value = color(value, theme, "#000000").slice(0, 7);
    input.setAttribute("aria-label", `主题色 ${name}`);
    input.addEventListener("change", () =>
      changeTheme((next) => (next.colors[name] = input.value)),
    );
    label.append(input, themeEntryActions("colors", name));
    $("theme-colors").append(label);
  }
  if (!Object.keys(theme.colors || {}).length)
    $("theme-colors").textContent = "暂无主题色";
  for (const [name, style] of Object.entries(theme.textStyles || {})) {
    const button = document.createElement("button");
    button.className = "theme-style-card";
    button.textContent = name;
    button.setAttribute("aria-label", `编辑主题样式 ${name}`);
    fontStyle(button, {
      ...textStyle(style, theme),
      fontSize: Math.min(24, style.fontSize || 16),
    });
    button.addEventListener("click", () => editThemeStyle(name));
    const row = document.createElement("div");
    row.className = "theme-style-row";
    row.append(button, themeEntryActions("textStyles", name));
    $("theme-styles").append(row);
  }
  if (!Object.keys(theme.textStyles || {}).length)
    $("theme-styles").textContent = "暂无文本样式";
  $("background-color").value = color(
    page().page.background?.color,
    theme,
    "#FFFFFF",
  ).slice(0, 7);
}
function themeEntryActions(kind, name) {
  const actions = document.createElement("div");
  actions.className = "theme-entry-actions";
  const title = kind === "colors" ? "主题色" : "文本样式";
  for (const [label, handler] of [
    ["编辑", () => kind === "colors" ? editThemeColor(name) : editThemeStyle(name)],
    ["删除", () => openThemeDelete(kind, name)],
  ]) {
    const button = document.createElement("button");
    button.textContent = label;
    button.setAttribute("aria-label", `${label}${title} ${name}`);
    if (label === "删除") button.className = "theme-delete-button";
    button.addEventListener("click", handler);
    actions.append(button);
  }
  return actions;
}
let editingColorName = null;
function editThemeColor(name) {
  editingColorName = name;
  $("color-name").value = name;
  $("color-value").value = color(project.deck.theme.colors[name], project.deck.theme, "#000000").slice(0, 7);
  $("color-dialog").showModal();
}
$("color-apply").addEventListener("click", () => {
  changeTheme(theme => { theme.colors[editingColorName] = $("color-value").value; });
  $("color-dialog").close();
});
let deletingThemeEntry = null;
function themeDeleteReferences(kind, name) {
  return themeEntryReferences(project.deck.theme, drafts.map(draft => draft.page), kind, name);
}
function openThemeDelete(kind, name) {
  deletingThemeEntry = {kind, name};
  const references = themeDeleteReferences(kind, name);
  $("theme-delete-message").textContent = `删除${kind === "colors" ? "主题色" : "文本样式"}“${name}”？可通过撤销恢复；保存主题后写入项目。`;
  $("theme-delete-error").textContent = references.length ? `此项仍被引用：${references.join("、")}。请先替换或移除这些引用，再删除。` : "";
  $("theme-delete-confirm").disabled = references.length > 0;
  $("theme-delete-dialog").showModal();
}
$("theme-delete-confirm").addEventListener("click", () => {
  const {kind, name} = deletingThemeEntry;
  if (hasPendingSource() || themeDeleteReferences(kind, name).length) {
    $("theme-delete-error").textContent = "请先应用页面源码，并替换或移除对此项的引用，再删除。";
    return;
  }
  changeTheme(theme => { delete theme[kind][name]; });
  $("theme-delete-dialog").close();
});
async function saveTheme() {
  if (!themeDirty()) return;
  const theme = clone(project.deck.theme || {});
  const result = await api("/api/save-theme", {
    theme,
    manifestHash: project.manifestHash,
  });
  project.manifestHash = result.manifestHash;
  savedTheme = JSON.stringify(theme);
}
$("save-theme").addEventListener("click", () =>
  action(async () => {
    await saveTheme();
    render();
    status("主题已保存到项目清单。");
  }),
);
$("open-theme").addEventListener("click", () => {
  closeMenus();
  $("theme-panel").hidden = false;
  $("element-panel").hidden = true;
  openInspector(true);
  renderTheme();
});
$("apply-theme").addEventListener("click", () => {
  try {
    const theme = JSON.parse($("theme-source").value);
    if (!theme || typeof theme !== "object" || Array.isArray(theme))
      throw new Error("主题必须是 JSON 对象。");
    if (
      Object.keys(theme).some(
        (key) => !["colors", "textStyles", "tableStyles"].includes(key),
      )
    )
      throw new Error("主题支持 colors、textStyles、tableStyles。");
    changeTheme((next) => {
      for (const key of Object.keys(next)) delete next[key];
      Object.assign(next, theme);
    });
  } catch (error) {
    showError(error);
  }
});
$("new-theme-color").addEventListener("click", () => {
  let n = 1;
  while (project.deck.theme?.colors?.[`accent${n}`]) n++;
  changeTheme((theme) => {
    theme.colors ||= {};
    theme.colors[`accent${n}`] = "#6956DE";
  });
});
let originalStyleName = null;
function editThemeStyle(name = null) {
  originalStyleName = name;
  const style = project.deck.theme?.textStyles?.[name] || {};
  $("style-name").value = name || "新样式";
  $("style-name").readOnly = name !== null;
  $("style-font").value =
    typeof style.fontFamily === "string"
      ? style.fontFamily
      : style.fontFamily?.latin || "Arial";
  $("style-size").value = style.fontSize || 28;
  $("style-color").value = color(
    style.color,
    project.deck.theme,
    "#172554",
  ).slice(0, 7);
  $("style-bold").checked = Boolean(style.bold);
  $("style-dialog").showModal();
}
$("new-text-style").addEventListener("click", () => editThemeStyle());
$("style-apply").addEventListener("click", () => {
  const name = $("style-name").value.trim(),
    font = $("style-font").value.trim(),
    size = Number($("style-size").value);
  if (!name || !font || !Number.isFinite(size) || size < 1 || size > 4000) {
    showError(new Error("请输入样式名称、字体和有效字号。"));
    return;
  }
  if (name !== originalStyleName && project.deck.theme?.textStyles?.[name]) {
    showError(new Error("样式名称已存在。"));
    return;
  }
  changeTheme((theme) => {
    theme.textStyles ||= {};
    const original = theme.textStyles[originalStyleName] || {};
    if (originalStyleName && name !== originalStyleName)
      throw new Error("已有样式名称用于页面引用，请保持名称不变。");
    theme.textStyles[name] = {
      ...original,
      fontFamily: font,
      fontSize: size,
      color: $("style-color").value,
      bold: $("style-bold").checked,
    };
  });
  $("style-dialog").close();
});
$("background-color").addEventListener("change", () => {
  const value = $("background-color").value;
  action(() =>
    edit((draft) => (draft.background = { type: "solid", color: value })),
  );
});
$("background-image").addEventListener("click", () => {
  $("background-file").value = "";
  $("background-file").click();
});
$("background-file").addEventListener("change", () =>
  action(async () => {
    const asset = await imageAsset($("background-file").files[0]);
    await edit(
      (draft) =>
        (draft.background = {
          type: "image",
          src: asset.path,
          fit: { mode: "cover" },
        }),
    );
  }),
);
$("background-all").addEventListener("click", () => {
  const background = clone(
    page().page.background || { type: "solid", color: "#FFFFFF" },
  );
  action(() =>
    editPages(
      drafts.map((_, i) => i),
      (draft) => (draft.background = clone(background)),
    ),
  );
});

function acceptProject(value) {
  for (const pending of images.values())
    pending.then((url) => URL.revokeObjectURL(url)).catch(() => {});
  images.clear();
  previewCache.clear();
  formulaCache.clear();
  project = value;
  drafts = value.pages.map((record) => new PageDraft(record));
  current = 0;
  selected = null;
  selectedIds.clear();
  pageSelection.clear();
  pageUndo = [];
  pageRedo = [];
  historyUndo = [];
  historyRedo = [];
  clipboard = null;
  zoom = null;
  watermarkLogo = null;
  themeUndo = [];
  themeRedo = [];
  savedTheme = JSON.stringify(value.deck.theme || {});
  syncThemeStyles();
  $("title").textContent = value.deck.title || value.manifest;
  $("project-path").textContent = value.imported
    ? `${value.manifest} · 工作副本`
    : value.manifest;
  $("local-project-path").value = value.root;
  render();
}
function requireSavedBeforeOpen() {
  if (
    !$("discard-project-drafts").checked &&
    (drafts.some((draft) => draft.dirty) ||
      themeDirty() ||
      hasPendingSource() ||
      pendingControls)
  )
    throw new Error(
      "当前项目有未保存草稿。请先保存或下载项目，再打开其他文件夹。",
    );
}
$("open-project").addEventListener("click", () => {
  $("discard-project-drafts").checked = false;
  $("project-dialog").showModal();
});
$("open-path").addEventListener("click", () =>
  action(async () => {
    requireSavedBeforeOpen();
    const result = await api("/api/open-project", {
      path: $("local-project-path").value.trim(),
    });
    acceptProject(result);
    $("project-dialog").close();
  }),
);
$("choose-project-folder").addEventListener("click", () => {
  $("project-folder").value = "";
  $("project-folder").click();
});
$("project-folder").addEventListener("change", () =>
  action(async () => {
    requireSavedBeforeOpen();
    const files = [...$("project-folder").files];
    if (!files.length) return;
    if (
      files.length > 2000 ||
      files.reduce((sum, file) => sum + file.size, 0) > 100 * 1024 * 1024
    )
      throw new Error("项目最多 2000 个文件、100 MiB。");
    const entries = [];
    for (const file of files)
      entries.push({
        path: file.webkitRelativePath.split("/").slice(1).join("/"),
        data: await encodeFile(file),
      });
    acceptProject(await api("/api/open-project", { files: entries }));
    $("project-dialog").close();
    status("本地项目已打开为工作副本；下载项目以带走全部修改。");
  }),
);
$("download-project").addEventListener("click", () =>
  action(async () => {
    if (pendingControls) throw new Error("请先提交属性输入。");
    await applySource();
    const blob = await api(
      "/api/download-project",
      {
        drafts: Object.fromEntries(
          drafts.map((draft) => [draft.path, draft.text]),
        ),
        hashes: Object.fromEntries(
          drafts.map((draft) => [draft.path, draft.hash]),
        ),
        manifestHash: project.manifestHash,
        theme: project.deck.theme || {},
      },
      true,
    );
    download(blob, project.manifest.replace(/\.pptd$/i, "-project.zip"));
    status("项目 ZIP 已生成，包含全部草稿、主题及引用资源。");
  }),
);

let previewIndex = 0,
  presentationVersion = 0,
  player = null,
  presentationLoading = false;
function fitPresentation() {
  if (!project || !$("presentation").open) return;
  const rect = $("presentation-viewport").getBoundingClientRect(),
    [w, h] = project.deck.size;
  $("presentation-slide").style.transform =
    `scale(${Math.max(0.02, Math.min((rect.width - 60) / w, (rect.height - 60) / h))})`;
}
async function showPresentation(index) {
  previewIndex = Math.max(0, Math.min(drafts.length - 1, index));
  const version = ++presentationVersion,
    record = drafts[previewIndex],
    slide = $("presentation-slide");
  presentationLoading = true;
  $("preview-next").disabled = true;
  player?.dispose();
  player = null;
  $("presentation-warning").hidden = true;
  slide.style.visibility = "visible";
  slide.replaceChildren();
  slide.style.width = `${project.deck.size[0]}px`;
  slide.style.height = `${project.deck.size[1]}px`;
  paint(slide, record.page.background || { type: "solid", color: "#FFFFFF" });
  for (const item of record.page.elements)
    slide.append(drawElement(item, false));
  updatePresentationCount();
  fitPresentation();
  if ($("slide-transition").value === "fade")
    slide.animate([{ opacity: 0 }, { opacity: 1 }], {
      duration: 250,
      easing: "ease-out",
    });
  try {
    const [result, timeline] = await Promise.all([
      record.page.elements.some((e) =>
        ["chart", "table"].includes(e.elementType),
      )
        ? previewFor(record)
        : Promise.resolve({ elements: {} }),
      api("/api/playback", { page: record.page }),
    ]);
    if (version !== presentationVersion || !$("presentation").open) return;
    for (const box of slide.children)
      if (result.elements[box.dataset.id])
        complexPreview(box, result.elements[box.dataset.id]);
    player = new Playback(
      timeline.groups,
      new Map([...slide.children].map((box) => [box.dataset.id, box])),
    );
    player.start();
    presentationLoading = false;
    updatePresentationCount();
  } catch (error) {
    if (version === presentationVersion) {
      presentationLoading = false;
      updatePresentationCount();
      $("presentation-warning").textContent =
        `本页动画无法播放：${error.message}`;
      $("presentation-warning").hidden = false;
    }
  }
}
function updatePresentationCount() {
  $("preview-count").textContent =
    `${previewIndex + 1} / ${drafts.length}${player?.groups.length ? ` · 动画 ${player.position}/${player.groups.length}` : ""}`;
  $("preview-prev").disabled = previewIndex === 0 && !player?.position;
  $("preview-next").disabled = presentationLoading;
}
function startPresentation(index) {
  return action(async () => {
    if (pendingControls) throw new Error("属性输入尚未成功提交，请检查输入。");
    await applySource();
    render();
    $("presentation").showModal();
    await showPresentation(index);
  });
}
function advancePresentation(direction = 1) {
  if (presentationLoading) return;
  if (player && (direction > 0 ? player.next() : player.previous())) {
    updatePresentationCount();
    return;
  }
  if (direction > 0 && previewIndex === drafts.length - 1) {
    $("presentation").close();
    return;
  }
  showPresentation(previewIndex + direction);
}
$("preview-deck").addEventListener("click", (event) =>
  startPresentation(event.shiftKey ? current : 0),
);
$("preview-prev").addEventListener("click", () => advancePresentation(-1));
$("preview-next").addEventListener("click", () => advancePresentation());
$("preview-restart").addEventListener("click", () =>
  showPresentation(previewIndex),
);
async function fullscreen(target) {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await target.requestFullscreen();
  } catch (error) {
    status("当前浏览器未允许系统全屏，仍可在窗口中播放。");
  }
}
$("preview-fullscreen").addEventListener("click", () =>
  fullscreen($("presentation")),
);
$("editor-fullscreen").addEventListener("click", () =>
  fullscreen(document.documentElement),
);
$("preview-close").addEventListener("click", () => $("presentation").close());
$("presentation").addEventListener("close", () => {
  presentationVersion++;
  player?.dispose();
  player = null;
  if (document.fullscreenElement === $("presentation"))
    document.exitFullscreen().catch(() => {});
});
$("presentation-viewport").addEventListener("click", () =>
  advancePresentation(),
);
$("presentation-viewport").addEventListener("contextmenu", (event) => {
  event.preventDefault();
  advancePresentation(-1);
});
$("presentation").addEventListener("keydown", (event) => {
  if (event.target.closest("select")) return;
  if (
    ["ArrowRight", "ArrowDown", " ", "PageDown", "Enter"].includes(event.key)
  ) {
    event.preventDefault();
    advancePresentation();
  }
  if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].includes(event.key)) {
    event.preventDefault();
    advancePresentation(-1);
  }
  if (event.key === "Home") {
    event.preventDefault();
    showPresentation(0);
  }
  if (event.key === "End") {
    event.preventDefault();
    showPresentation(drafts.length - 1);
  }
  if (["b", "w"].includes(event.key.toLowerCase())) {
    event.preventDefault();
    $("presentation-slide").style.visibility =
      $("presentation-slide").style.visibility === "hidden"
        ? "visible"
        : "hidden";
    $("presentation").style.background =
      event.key.toLowerCase() === "w" ? "white" : "#151519";
  }
});
new ResizeObserver(fitPresentation).observe($("presentation-viewport"));
action(async () => {
  acceptProject(await api("/api/project"));
  api("/api/fonts")
    .then(({ families }) => {
      for (const name of families) {
        const option = document.createElement("option");
        option.value = name;
        $("font-families").append(option);
      }
    })
    .catch(() => {
      $("font-family").title =
        "字体列表未能读取，可手动输入字体名称。";
    });
  $("title").textContent = project.deck.title || project.manifest;
  $("project-path").textContent = project.manifest;
  render();
});

// Page structure is committed independently of page drafts. Removed YAML files
// remain on disk so structural undo can restore the same paths and resources.
const popup = new Popup((task) => action(task));
installIcons();
function exportSnapshot() {
  return {
    drafts: Object.fromEntries(drafts.map((d) => [d.path, d.text])),
    hashes: Object.fromEntries(drafts.map((d) => [d.path, d.hash])),
    manifestHash: project.manifestHash,
    theme: project.deck.theme || {},
  };
}
async function arrangePages(entries, focus, record = true) {
  const before = {
    paths: drafts.map((d) => d.path),
    records: [...drafts],
    current,
  };
  const result = await api("/api/arrange-pages", {
    pages: entries,
    hashes: Object.fromEntries(
      [
        ...pageUndo.flatMap((s) => s.records),
        ...pageRedo.flatMap((s) => s.records),
        ...drafts,
      ].map((d) => [d.path, d.hash]),
    ),
    manifestHash: project.manifestHash,
  });
  const retained = new Map(drafts.map((d) => [d.path, d]));
  drafts = result.pages.map((d) => {
    const draft = retained.get(d.path) || new PageDraft(d);
    draft.saved(d.hash, d.text);
    return draft;
  });
  project.manifestHash = result.manifestHash;
  project.deck.pages = result.deck.pages;
  project.pages = result.pages;
  current = Math.max(0, Math.min(focus, drafts.length - 1));
  selected = null;
  selectedIds.clear();
  pageSelection = new Set([current]);
  if (record) {
    pageUndo.push(before);
    if (pageUndo.length > 50) pageUndo.shift();
    pageRedo = [];
    recordHistory({ kind: "structure" });
  }
  render();
}
async function travelPages(command) {
  const from = command === "undo" ? pageUndo : pageRedo,
    to = command === "undo" ? pageRedo : pageUndo;
  if (!from.length) return;
  const state = from.at(-1),
    before = {
      paths: drafts.map((d) => d.path),
      records: [...drafts],
      current,
    };
  await arrangePages(state.paths, state.current, false);
  from.pop();
  to.push(before);
  const records = new Map(state.records.map((d) => [d.path, d]));
  drafts = drafts.map((d) => {
    const record = records.get(d.path);
    if (record) {
      record.saved(d.hash, d.savedText);
      return record;
    }
    return d;
  });
  render();
}
async function newPage(copy = false) {
  await applySource();
  const entries = drafts.map((d) => d.path);
  entries.splice(
    current + 1,
    0,
    copy
      ? clone(page().page)
      : { background: { type: "solid", color: "#FFFFFF" }, elements: [] },
  );
  await arrangePages(entries, current + 1);
  status(copy ? "页面已复制" : "空白页面已创建");
}
$("new-page").addEventListener("click", () => action(() => newPage()));
function selectionPages() {
  return [...(pageSelection.size ? pageSelection : new Set([current]))].sort(
    (a, b) => a - b,
  );
}
async function deletePages() {
  await applySource();
  const chosen = new Set(selectionPages());
  const paths = drafts.filter((_, i) => !chosen.has(i)).map((d) => d.path);
  await arrangePages(
    paths.length
      ? paths
      : [{ background: { type: "solid", color: "#FFFFFF" }, elements: [] }],
    Math.min(...chosen),
  );
}
function copyElements() {
  clipboard = {
    kind: "elements",
    items: clone(
      page().page.elements.filter((e) => selectedIds.has(e.elementId)),
    ),
    animations: clone(
      (page().page.animations || []).filter((e) =>
        selectedIds.has(e.elementId),
      ),
    ),
  };
  status(`已复制 ${clipboard.items.length} 个元素`);
}
async function paste() {
  if (!clipboard) return;
  if (clipboard.kind === "pages") {
    const entries = drafts.map((d) => d.path);
    entries.splice(current + 1, 0, ...clone(clipboard.items));
    await arrangePages(entries, current + 1);
    return;
  }
  await edit((value) => {
    const remap = new Map();
    selectedIds.clear();
    for (const source of clipboard.items) {
      const item = clone(source);
      let n = 1;
      while (
        value.elements.some(
          (e) => e.elementId === `${source.elementId}-copy-${n}`,
        )
      )
        n++;
      item.elementId = `${source.elementId}-copy-${n}`;
      remap.set(source.elementId, item.elementId);
      item.bounds[0] += 20;
      item.bounds[1] += 20;
      value.elements.push(item);
      selectedIds.add(item.elementId);
    }
    if (clipboard.animations.length) {
      value.animations ??= [];
      value.animations.push(
        ...clipboard.animations.map((a) => ({
          ...clone(a),
          elementId: remap.get(a.elementId),
        })),
      );
    }
    selected = [...selectedIds].at(-1) || null;
  });
}
async function deleteElements() {
  const ids = [...selectedIds];
  await edit((value) => {
    for (const id of ids) deleteElement(value, id);
    selectedIds.clear();
    selected = null;
  });
}
async function order(direction) {
  const ids = new Set(selectedIds);
  await edit((value) => {
    const chosen = value.elements.filter((e) => ids.has(e.elementId)),
      rest = value.elements.filter((e) => !ids.has(e.elementId));
    if (direction === "front") value.elements = [...rest, ...chosen];
    else if (direction === "back") value.elements = [...chosen, ...rest];
    else {
      const list = direction === 1 ? [...chosen].reverse() : chosen;
      for (const item of list) moveLayer(value, item.elementId, direction);
    }
  });
}
async function alignSelection(kind) {
  const ids = new Set(selectedIds);
  await edit((value) => {
    const items = value.elements.filter((e) => ids.has(e.elementId));
    const box =
      items.length > 1
        ? [
            Math.min(...items.map((e) => e.bounds[0])),
            Math.min(...items.map((e) => e.bounds[1])),
            Math.max(...items.map((e) => e.bounds[0] + e.bounds[2])),
            Math.max(...items.map((e) => e.bounds[1] + e.bounds[3])),
          ]
        : [0, 0, ...project.deck.size];
    for (const item of items) {
      const b = item.bounds;
      if (kind === "left") b[0] = box[0];
      if (kind === "center") b[0] = (box[0] + box[2] - b[2]) / 2;
      if (kind === "right") b[0] = box[2] - b[2];
      if (kind === "top") b[1] = box[1];
      if (kind === "middle") b[1] = (box[1] + box[3] - b[3]) / 2;
      if (kind === "bottom") b[1] = box[3] - b[3];
    }
  });
}
const entry = (label, action, hint = "", disabled = false) => ({
  label,
  action,
  hint,
  disabled,
});
const selectAll = () => {
  selectedIds = new Set(page().page.elements.map((e) => e.elementId));
  selected = [...selectedIds].at(-1) || null;
  select(selected, false, true);
};
const layerEntries = () => [
  entry("上移一层", () => order(1)),
  entry("下移一层", () => order(-1)),
  entry("置于顶层", () => order("front")),
  entry("置于底层", () => order("back")),
];
function contextEntries(kind) {
  const pasteEntry = entry("粘贴", paste, "⌘ / Ctrl + V", !clipboard);
  if (kind === "page")
    return [
      entry(
        "剪切",
        async () => {
          await applySource();
          clipboard = {
            kind: "pages",
            items: selectionPages().map((i) => clone(drafts[i].page)),
          };
          await deletePages();
        },
        "⌘ / Ctrl + X",
      ),
      entry(
        "复制",
        async () => {
          await applySource();
          clipboard = {
            kind: "pages",
            items: selectionPages().map((i) => clone(drafts[i].page)),
          };
        },
        "⌘ / Ctrl + C",
      ),
      pasteEntry,
      entry(
        "全选",
        () => {
          pageSelection = new Set(drafts.map((_, i) => i));
          render();
        },
        "⌘ / Ctrl + A",
      ),
      null,
      entry("新建页面", () => newPage()),
      entry("复制页面", () => newPage(true)),
      entry("删除页面", deletePages, "Delete"),
      null,
      entry("从当前页开始放映", () => {
        startPresentation(current);
      }),
    ];
  if (kind === "element")
    return [
      entry(
        "剪切",
        async () => {
          copyElements();
          await deleteElements();
        },
        "⌘ / Ctrl + X",
      ),
      entry("复制", copyElements, "⌘ / Ctrl + C"),
      pasteEntry,
      entry("删除", deleteElements, "Delete"),
      null,
      ...layerEntries(),
      null,
      entry("对齐 ›", () =>
        popup.show(
          ["left", "center", "right", "top", "middle", "bottom"].map((v, i) =>
            entry(
              ["左对齐", "水平居中", "右对齐", "顶对齐", "垂直居中", "底对齐"][
                i
              ],
              () => alignSelection(v),
            ),
          ),
          parseFloat(popup.node.style.left) + 240,
          parseFloat(popup.node.style.top),
        ),
      ),
    ];
  return [
    pasteEntry,
    entry("全选", selectAll, "⌘ / Ctrl + A"),
    entry("修改背景", () => {
      $("open-theme").click();
    }),
    null,
    entry("从当前页开始放映", () => {
      startPresentation(current);
    }),
  ];
}
$("pages").addEventListener("contextmenu", (event) => {
  const target = event.target.closest("button[data-page]");
  if (!target) return;
  event.preventDefault();
  action(async () => {
    await applySource();
    current = Number(target.dataset.page);
    selectedIds.clear();
    selected = null;
    if (!pageSelection.has(current)) pageSelection = new Set([current]);
    render();
    popup.show(contextEntries("page"), event.clientX, event.clientY);
  });
});
$("viewport").addEventListener("contextmenu", (event) => {
  if (textSession?.root.contains(event.target)) return;
  event.preventDefault();
  const target = event.target.closest(".element");
  if (target)
    select(target.dataset.id, false, selectedIds.has(target.dataset.id));
  else select(null);
  popup.show(
    contextEntries(target ? "element" : "canvas"),
    event.clientX,
    event.clientY,
  );
});
document.addEventListener("keydown", (event) => {
  if (
    event.target.closest("input,textarea,[contenteditable]") ||
    document.querySelector("dialog[open]") ||
    !(event.metaKey || event.ctrlKey) ||
    event.altKey
  )
    return;
  const key = event.key.toLowerCase();
  if (!["c", "x", "v", "a"].includes(key)) return;
  event.preventDefault();
  const pages = event.target.closest("#page-sidebar");
  action(async () => {
    await applySource();
    if (key === "v") await paste();
    else if (pages) {
      if (key === "a") {
        pageSelection = new Set(drafts.map((_, i) => i));
        render();
      } else {
        clipboard = {
          kind: "pages",
          items: selectionPages().map((i) => clone(drafts[i].page)),
        };
        if (key === "x") await deletePages();
      }
    } else if (key === "a") selectAll();
    else {
      copyElements();
      if (key === "x") await deleteElements();
    }
  });
});
function contentUpdate(key, value) {
  if (
    [
      "backgroundColor",
      "color",
      "fontFamily",
      "fontSize",
      "bold",
      "italic",
      "underline",
      "strike",
    ].includes(key) &&
    applyInlineText({ [key]: value })
  )
    return;
  return edit((draft) => {
    const item = draft.elements.find((e) => e.elementId === selected);
    if (key === "lineHeight") delete item.content.lineHeightPx;
    formatText(item.content, key, value);
  });
}
for (const [id, axis, values, labels] of [
  [
    "text-horizontal",
    0,
    ["left", "center", "right", "justify", "distributed"],
    ["左对齐", "居中", "右对齐", "两端对齐", "分散对齐"],
  ],
  ["text-vertical", 1, ["top", "middle", "bottom"], ["顶部", "中部", "底部"]],
])
  $(id).addEventListener("click", () =>
    popup.below(
      $(id),
      values.map((v, i) =>
        entry(labels[i], () => {
          const align = [
            ...(textStyle(element().content, project.deck.theme).align || [
              "left",
              "top",
            ]),
          ];
          align[axis] = v;
          return contentUpdate("align", align);
        }),
      ),
    ),
  );
$("text-spacing").addEventListener("click", () =>
  popup.below(
    $("text-spacing"),
    [1, 1.2, 1.5, 2, 2.5, 3].map((value) =>
      entry(`${value} 倍行距`, () => contentUpdate("lineHeight", value)),
    ),
  ),
);
async function openTextFormula() {
  if (busy || element()?.elementType !== "text") return;
  const id = selected;
  const bookmark = textSession?.capture();
  if (textSession) await finishTextEdit(true);
  if (textSession) return;
  const item = page().page.elements.find((e) => e.elementId === id);
  const paragraphs = readParagraphs(String(item.content.text ?? ""));
  const plain = paragraphs
    .flatMap((p) => p.runs.map((r) => r.text || ""))
    .join("");
  const matches = [...plain.matchAll(/\\\(([\s\S]*?)\\\)/g)];
  formulaTarget = {
    id,
    matches,
    range: bookmark
      ? [
          Math.min(bookmark.anchor, bookmark.focus),
          Math.max(bookmark.anchor, bookmark.focus),
        ]
      : [plain.length, plain.length],
  };
  const list = $("formula-location");
  list.replaceChildren(
    new Option(bookmark ? "在光标 / 选区处插入" : "在文末插入", "new"),
  );
  matches.forEach((match, i) =>
    list.add(new Option(`公式 ${i + 1}：${match[1]}`, String(i))),
  );
  list.value = !bookmark && matches.length ? "0" : "new";
  $("formula-location-row").hidden = false;
  $("formula-title").textContent = "文字框公式";
  setFormulaLocation();
  controls.sync();
  $("formula-dialog").showModal();
}
function setFormulaLocation() {
  const match = formulaTarget?.matches[Number($("formula-location").value)];
  $("formula-source").value = match ? match[1] : "E = mc^2";
  $("formula-apply").textContent = match ? "更新公式" : "插入到文字框";
  updateFormula();
}
$("formula-location").addEventListener("change", setFormulaLocation);
$("text-fx").addEventListener("click", () =>
  openTextFormula().catch(showError),
);
function applyScript(script) {
  if (applyInlineText({ script })) return;
  return edit((draft) => {
    const content = draft.elements.find(
      (e) => e.elementId === selected,
    ).content;
    content.text = writeParagraphs(
      formatSelection(readParagraphs(String(content.text ?? "")), 0, Infinity, {
        script,
      }),
    );
  });
}
$("text-script").addEventListener("click", () =>
  popup.below($("text-script"), [
    entry("上标  x²", () => applyScript("sup")),
    entry("下标  x₂", () => applyScript("sub")),
    entry("正常基线", () => applyScript(null)),
  ]),
);
for (const prefix of ["text", "shape"]) {
  $(`${prefix}-layer`).addEventListener("click", () =>
    popup.below($(`${prefix}-layer`), layerEntries()),
  );
  $(`${prefix}-opacity`).addEventListener("click", () =>
    popup.below(
      $(`${prefix}-opacity`),
      [0, 0.25, 0.5, 0.75, 1].map((opacity) =>
        entry(`${opacity * 100}% 不透明度`, () =>
          edit(
            (value) =>
              (value.elements.find((e) => e.elementId === selected).opacity =
                opacity),
          ),
        ),
      ),
    ),
  );
}
for (const [id, index] of [
  ["shape-flip-h", 0],
  ["shape-flip-v", 1],
])
  $(id).addEventListener("click", () =>
    action(() =>
      edit((value) => {
        const item = value.elements.find((e) => e.elementId === selected);
        item.flip = [...(item.flip || [false, false])];
        item.flip[index] = !item.flip[index];
      }),
    ),
  );
$("shape-fill").addEventListener("change", () => {
  const color = $("shape-fill").value;
  action(() =>
    edit(
      (value) =>
        (value.elements.find((e) => e.elementId === selected).fill = {
          type: "solid",
          color,
        }),
    ),
  );
});
$("shape-fill-options").addEventListener("click", () =>
  popup.below($("shape-fill-options"), [
    entry("无填充", () =>
      edit(
        (value) =>
          delete value.elements.find((e) => e.elementId === selected).fill,
      ),
    ),
    ...Object.entries(project.deck.theme?.colors || {}).map(([name, color]) =>
      entry(name, () =>
        edit(
          (value) =>
            (value.elements.find((e) => e.elementId === selected).fill = {
              type: "solid",
              color,
            }),
        ),
      ),
    ),
  ]),
);
$("shape-border").addEventListener("click", () =>
  popup.below($("shape-border"), [
    entry("无边框", () =>
      edit(
        (value) =>
          delete value.elements.find((e) => e.elementId === selected).border,
      ),
    ),
    ...[1, 2, 4, 6].map((width) =>
      entry(`${width}px 实线`, () =>
        edit((value) => {
          const item = value.elements.find((e) => e.elementId === selected);
          item.border = {
            color: item.border?.color || "#191919",
            style: "solid",
            width,
          };
        }),
      ),
    ),
    ...["dash", "dot"].map((style) =>
      entry(style === "dash" ? "虚线" : "点线", () =>
        edit((value) => {
          const item = value.elements.find((e) => e.elementId === selected);
          item.border = {
            color: item.border?.color || "#191919",
            width: item.border?.width || 2,
            style,
          };
        }),
      ),
    ),
  ]),
);
$("shape-replace").addEventListener("click", () => {
  replacingShape = true;
  shapeChoices();
  $("shape-menu").hidden = false;
});
$("add-shape").addEventListener(
  "click",
  () => {
    replacingShape = false;
  },
  true,
);
function beginRotate(event, box, item) {
  event.stopPropagation();
  if (busy || event.button !== 0 || hasPendingSource()) return;
  event.preventDefault();
  const textEdit = detachTextForGesture();
  select(item.elementId);
  const rect = box.getBoundingClientRect(),
    center = [(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2],
    initial = Math.atan2(event.clientY - center[1], event.clientX - center[0]);
  const handle = event.currentTarget;
  handle.setPointerCapture(event.pointerId);
  let rotation = Number(item.rotation || 0);
  const move = (e) => {
    rotation =
      Number(item.rotation || 0) +
      ((Math.atan2(e.clientY - center[1], e.clientX - center[0]) - initial) *
        180) /
        Math.PI;
    if (e.shiftKey) rotation = Math.round(rotation / 15) * 15;
    box.style.transform = `rotate(${rotation}deg) scale(${item.flip?.[0] ? -1 : 1},${item.flip?.[1] ? -1 : 1})`;
  };
  const stop = (e) => {
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", stop);
    handle.removeEventListener("pointercancel", stop);
    if (handle.hasPointerCapture(event.pointerId))
      handle.releasePointerCapture(event.pointerId);
    if (e.type === "pointercancel") {
      commitCanvasGesture(textEdit, null, true);
      return;
    }
    commitCanvasGesture(
      textEdit,
      (value) =>
        (value.elements.find((e) => e.elementId === item.elementId).rotation =
          Math.round(rotation * 100) / 100),
    );
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
}
const inlineControlIds = new Set([
  "text-fx",
  "text-script",
  "font-family",
  "font-size",
  "text-color",
  "text-highlight",
  "text-bold",
  "text-italic",
  "text-underline",
  "text-strike",
  "clear-highlight",
  "undo",
  "redo",
]);
// Defer committing text until the pointer gesture ends. Serializing/rebuilding
// the canvas during pointerdown destroys the target and its pointer capture.
function detachTextForGesture() {
  const session = textSession;
  if (!session) return null;
  const html = session.html();
  session.capture();
  session.close();
  textSession = null;
  return { session, html, dirty: html !== session.initial };
}
function restoreTextSession(session) {
  if (!session.root.isConnected) return;
  const resumed = new TextEditingSession(
    session.root,
    session.initial,
    textSessionChanged,
    finishTextEdit,
    { preserveDOM: true, ...session.viewOptions },
  );
  resumed.elementId = session.elementId;
  resumed.undo = session.undo;
  resumed.redo = session.redo;
  resumed.bookmark = session.bookmark;
  restoreTextBookmark(session.root, resumed.bookmark);
  textSession = resumed;
  textSessionChanged();
}
function commitCanvasGesture(textEdit, update = null, resetPreview = false) {
  if (!textEdit?.dirty && !update) {
    if (textEdit || resetPreview) render();
    return;
  }
  action(async () => {
    try {
      if (textEdit?.dirty)
        await edit(
          (draft) => {
            const item = draft.elements.find(
              (e) => e.elementId === textEdit.session.elementId,
            );
            if (!item) throw new Error("文字元素已移除，无法提交编辑。");
            item.content.text = textEdit.html;
          },
          { render: false },
        );
    } catch (error) {
      if (textEdit) restoreTextSession(textEdit.session);
      throw error;
    }
    // Text and geometry remain two independent undo steps, but neither rebuilds
    // the captured DOM until the gesture has finished.
    if (update) await edit(update);
    else render();
  });
}
function isInlineControl(node) {
  const owner = node?.closest?.("[data-control-owner]")?.dataset.controlOwner;
  if (owner && inlineControlIds.has(owner)) return true;
  const control = node?.closest?.("button,input");
  return control && inlineControlIds.has(control.id);
}
function applyInlineText(changes) {
  if (!textSession) return false;
  try {
    textSession.apply(changes);
    pendingControls = false;
    refreshControls();
  } catch (error) {
    showError(error);
  }
  return true;
}
function inspectTextSelection() {
  if (!textSession) return;
  const state = textSession.state(),
    base = textStyle(element().content, project.deck.theme);
  for (const [key, id] of [
    ["fontFamily", "font-family"],
    ["fontSize", "font-size"],
    ["color", "text-color"],
    ["backgroundColor", "text-highlight"],
  ]) {
    if (document.activeElement === $(id)) continue;
    let value = state[key] ?? base[key];
    if (key === "fontFamily" && typeof value === "object")
      value = value.latin || value.ea;
    $(id).dataset.mixed = String(value === "mixed");
    if (value === "mixed") {
      if (!id.includes("color") && id !== "text-highlight") {
        $(id).value = "";
        $(id).placeholder = "混合";
      }
      continue;
    }
    if (key === "fontSize") value = parseFloat(value);
    if (key.includes("Color") || key === "color")
      value = color(value, project.deck.theme, "#FFFF00").slice(0, 7);
    if (value !== undefined) $(id).value = value;
    $(id).placeholder = "";
  }
  $("text-color").nextElementSibling.style.setProperty(
    "--icon-color",
    $("text-color").value,
  );
  $("text-highlight").nextElementSibling.style.setProperty(
    "--icon-highlight",
    color(
      state.backgroundColor === "mixed"
        ? undefined
        : (state.backgroundColor ?? base.backgroundColor),
      project.deck.theme,
      "transparent",
    ),
  );
  for (const key of ["bold", "italic", "underline", "strike"]) {
    const value = state[key] ?? Boolean(base[key]);
    $("text-" + key).setAttribute(
      "aria-pressed",
      value === "mixed" ? "mixed" : String(Boolean(value)),
    );
  }
}
function textSessionChanged() {
  pendingControls = false;
  status(textSession?.dirty ? "文字编辑中 · 尚未保存" : "文字编辑中");
  inspectTextSelection();
  refreshControls();
  if (!textSession) return;
  const thumbnailPage = [
    ...$("pages").querySelectorAll("button[data-page]"),
  ].find((node) => Number(node.dataset.page) === current);
  const thumbnail = [...(thumbnailPage?.querySelectorAll(".element") || [])]
    .find((node) => node.dataset.id === selected)
    ?.querySelector(".content>div");
  if (thumbnail) {
    thumbnail.replaceChildren();
    richText(
      textSession.html(),
      thumbnail,
      textSession.viewOptions.inheritedHighlight,
    );
  }
}
function finishTextEdit(commit = true, save = false) {
  const session = textSession;
  if (!session) return;
  let value;
  try {
    value = session.html();
  } catch (error) {
    showError(error);
    return;
  }
  textSession = null;
  session.close();
  const changed = commit && value !== session.initial;
  const task = changed
    ? action(async () => {
        try {
          await edit((draft) => {
            const item = draft.elements.find(
              (e) => e.elementId === session.elementId,
            );
            if (!item) throw new Error("文字元素已移除，无法提交编辑。");
            item.content.text = value;
          });
        } catch (error) {
          restoreTextSession(session);
          throw error;
        }
      })
    : Promise.resolve();
  if (!changed) render();
  if (save) task.then(() => $("save").click());
  return task;
}
document.addEventListener("selectionchange", () => {
  if (textSession) {
    inspectTextSelection();
    controls.sync();
  }
});
document.addEventListener(
  "pointerdown",
  (event) => {
    if (!textSession || textSession.root.contains(event.target)) return;
    if (event.button === 0 && event.target.closest("#stage .element")) return;
    if (isInlineControl(event.target)) {
      textSession.capture();
      if (event.target.closest("button")) event.preventDefault();
      return;
    }
    finishTextEdit(true);
  },
  true,
);
document.addEventListener("focusin", (event) => {
  if (
    textSession &&
    !textSession.root.contains(event.target) &&
    !isInlineControl(event.target)
  )
    finishTextEdit(true);
});
function beginTextEdit(box, item) {
  if (busy || hasPendingSource() || textSession) return;
  if (String(item.content.text).includes("\\(")) {
    $("theme-panel").hidden = true;
    $("element-panel").hidden = false;
    openInspector(true);
    $("text-label").open = true;
    $("text").focus();
    return;
  }
  const target = box.querySelector(".content>div");
  try {
    textSession = new TextEditingSession(
      target,
      item.content.text,
      textSessionChanged,
      finishTextEdit,
      {
        preserveDOM: target.dataset.editable === "true",
        inheritedHighlight: color(
          textStyle(item.content, project.deck.theme).backgroundColor,
          project.deck.theme,
        ),
      },
    );
    textSession.elementId = item.elementId;
    textSessionChanged();
  } catch (error) {
    showError(error);
  }
}
function recordHistory(entry) {
  historyUndo.push(entry);
  if (historyUndo.length > 50) historyUndo.shift();
  historyRedo = [];
}
async function travelHistory(command) {
  const from = command === "undo" ? historyUndo : historyRedo,
    to = command === "undo" ? historyRedo : historyUndo;
  const entry = from.at(-1);
  if (!entry) return;
  if (entry.kind === "structure") await travelPages(command);
  else {
    for (const draft of entry.drafts) draft[command]();
    const index = drafts.indexOf(entry.drafts[0]);
    if (index >= 0) current = index;
    selected = null;
    selectedIds.clear();
  }
  from.pop();
  to.push(entry);
}

function slideImage(record) {
  return exportSlideImage(project, record, {
    paint,
    drawElement,
    complexPreview,
    previewFor,
    api,
    formulaCache,
  });
}

$("save-all").addEventListener("click", () =>
  action(async () => {
    if (pendingControls) throw new Error("请先提交属性输入。");
    await applySource();
    for (const draft of drafts)
      if (draft.dirty) {
        const result = await api("/api/save", {
          path: draft.path,
          text: draft.text,
          hash: draft.hash,
          manifestHash: project.manifestHash,
        });
        draft.saved(result.hash, draft.text);
      }
    await saveTheme();
    render();
    status("所有页面和主题已保存");
  }),
);

$("page-sidebar").addEventListener("keydown", (event) => {
  if (
    ["Delete", "Backspace"].includes(event.key) &&
    !document.querySelector("dialog[open]")
  ) {
    event.preventDefault();
    action(deletePages);
  }
});

// Accessibility input methods may emit input without the native change event.
// Commit once on blur; native change clears the flag before its target handler.
const blurCommitIds = new Set([
  "x",
  "y",
  "width",
  "height",
  "rotation",
  "font-size",
  "text",
  "fill",
  "font-family",
  "text-color",
  "text-highlight",
  "notes",
  "shape-fill",
]);
document.addEventListener("input", (event) => {
  if (blurCommitIds.has(event.target.id))
    event.target.dataset.pendingSubmit = "true";
});
document.addEventListener(
  "change",
  (event) => {
    if (blurCommitIds.has(event.target.id))
      delete event.target.dataset.pendingSubmit;
  },
  true,
);
document.addEventListener(
  "blur",
  (event) => {
    if (
      blurCommitIds.has(event.target.id) &&
      event.target.dataset.pendingSubmit
    ) {
      delete event.target.dataset.pendingSubmit;
      event.target.dispatchEvent(new Event("change", { bubbles: true }));
    }
  },
  true,
);

$("text-expand").addEventListener("click", () => {
  const expanded = $("text-tools").classList.toggle("expanded");
  $("text-expand").setAttribute("aria-expanded", String(expanded));
  $("text-expand").setAttribute(
    "aria-label",
    expanded ? "收起文字工具栏" : "展开文字工具栏",
  );
});
