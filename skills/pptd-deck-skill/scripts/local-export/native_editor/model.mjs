// Independently authored editor state. No upstream implementation is included.
import { SHAPES } from "./shapes.mjs";
const previewShapes = new Set(SHAPES.map(([name]) => name));
export const clone = (value) => structuredClone(value);

// A blur-triggered property edit must finish before a following Save click.
// Keep the queue alive after errors so a failed export cannot freeze editing.
export class SerialActions {
  constructor() {
    this.tail = Promise.resolve();
    this.revision = 0;
  }
  run(task) {
    const revision = this.revision;
    const pending = this.tail.then(() => {
      if (revision !== this.revision)
        throw new Error("前一项操作失败，后续动作已取消。请检查输入后重试。");
      return task();
    });
    this.tail = pending.catch(() => {
      this.revision++;
    });
    return pending;
  }
}

export class PageDraft {
  constructor(record) {
    Object.assign(this, clone(record));
    this.savedText = this.text;
    this.undoStack = [];
    this.redoStack = [];
  }
  get dirty() {
    return this.text !== this.savedText;
  }
  snapshot() {
    return { text: this.text, page: clone(this.page) };
  }
  change(text, page) {
    if (text === this.text) return;
    this.undoStack.push(this.snapshot());
    if (this.undoStack.length > 50) this.undoStack.shift();
    this.redoStack = [];
    this.text = text;
    this.page = clone(page);
  }
  travel(from, to) {
    if (!from.length) return false;
    to.push(this.snapshot());
    Object.assign(this, from.pop());
    return true;
  }
  undo() {
    return this.travel(this.undoStack, this.redoStack);
  }
  redo() {
    return this.travel(this.redoStack, this.undoStack);
  }
  saved(hash, text) {
    this.hash = hash;
    this.savedText = text;
  }
}

export function color(value, theme, fallback = "transparent") {
  const seen = new Set();
  while (typeof value === "string" && value.startsWith("$")) {
    if (seen.has(value)) return fallback;
    seen.add(value);
    value = theme?.colors?.[value.slice(1)];
  }
  return typeof value === "string" && /^#[\da-f]{6}([\da-f]{2})?$/i.test(value)
    ? value
    : fallback;
}

export function textStyle(content, theme, defaultFamily = "MiSans") {
  const inherited =
    typeof content?.style === "string" && content.style.startsWith("$")
      ? theme?.textStyles?.[content.style.slice(1)]
      : {};
  const result = {
    fontSize: 16,
    fontFamily: defaultFamily,
    color: "#333333",
    lineHeight: 1.2,
    ...inherited,
    ...content,
  };
  if (content?.lineHeight !== undefined && content?.lineHeightPx === undefined)
    delete result.lineHeightPx;
  return result;
}

export function setTableCellText(table, row, index, text) {
  const cell = table.rows[row][index];
  if (typeof cell === "string") table.rows[row][index] = text;
  else cell.text = text;
}

export function newElement(page, kind) {
  let i = 1;
  while (page.elements.some((e) => e.elementId === `${kind}-${i}`)) i++;
  const base = {
    elementId: `${kind}-${i}`,
    elementType: kind,
    bounds: [60, 60, 300, 80],
  };
  if (kind === "text")
    return {
      ...base,
      content: {
        text: "输入文字",
        fontSize: 28,
        fontFamily: "Arial",
        color: "#172554",
      },
    };
  if (kind === "shape")
    return {
      ...base,
      shapeName: "rect",
      fill: { type: "solid", color: "#2563EB" },
    };
  if (kind === "table")
    return {
      ...base,
      bounds: [60, 60, 480, 180],
      columnWidths: [0.5, 0.5],
      rowHeights: [0.5, 0.5],
      rows: [
        [{ text: "A1" }, { text: "B1" }],
        [{ text: "A2" }, { text: "B2" }],
      ],
      style: {
        cellStyle: {
          fontFamily: "Arial",
          fontSize: 20,
          border: { color: "#94A3B8", width: 1, style: "solid" },
        },
      },
    };
  if (kind === "chart")
    return {
      ...base,
      bounds: [60, 60, 520, 300],
      data: {
        cols: ["Category", "Value"],
        rows: [
          ["A", 10],
          ["B", 20],
          ["C", 15],
        ],
      },
      series: [
        {
          type: "bar",
          encode: { x: "Category", y: "Value" },
          name: "Value",
          fill: "#2563EB",
        },
      ],
      xAxis: { type: "category" },
      yAxis: { type: "value" },
      legend: { show: false },
    };
  if (kind === "image") return { ...base, fit: { mode: "contain" } };
  if (kind === "line")
    return {
      ...base,
      bounds: [60, 60, 300, 80],
      viewBox: [100, 100],
      points: "0,50 100,50",
      curve: "sharp",
      border: { color: "#172554", width: 2, style: "solid" },
    };
  throw new Error(`未支持的插入类型：${kind}`);
}

export function deleteElement(page, identifier) {
  if (!page.elements.some((item) => item.elementId === identifier))
    throw new Error("请选择要删除的元素。");
  page.elements = page.elements.filter((item) => item.elementId !== identifier);
  if (Array.isArray(page.animations))
    page.animations = page.animations.filter(
      (item) => item.elementId !== identifier,
    );
}

// Dragging divides screen deltas by this same scale. Manual zoom remains
// stable across window resizes; automatic fit avoids cropping the slide.
export function canvasScale(size, viewport, zoom = null) {
  return zoom === null
    ? Math.max(
        0.02,
        Math.min(
          (viewport[0] - 24) / size[0],
          (viewport[1] - 24) / size[1],
          1.5,
        ),
      )
    : Math.max(0.1, Math.min(4, zoom));
}

export function moveLayer(page, identifier, direction) {
  const index = page.elements.findIndex(
    (item) => item.elementId === identifier,
  );
  if (index < 0) throw new Error("请选择要调整的元素。");
  const target = Math.max(
    0,
    Math.min(page.elements.length - 1, index + direction),
  );
  if (target === index) return;
  const [item] = page.elements.splice(index, 1);
  page.elements.splice(target, 0, item);
}

export function resizeBounds(
  bounds,
  rotation,
  flip,
  delta,
  axes = "se",
  proportional = false,
) {
  const angle = (rotation * Math.PI) / 180,
    c = Math.cos(angle),
    s = Math.sin(angle);
  const fx = flip?.[0] ? -1 : 1,
    fy = flip?.[1] ? -1 : 1;
  const sx = axes.includes("w") ? -1 : axes.includes("e") ? 1 : 0;
  const sy = axes.includes("n") ? -1 : axes.includes("s") ? 1 : 0;
  let dw = sx * (c * delta[0] + s * delta[1]) * fx;
  let dh = sy * (-s * delta[0] + c * delta[1]) * fy;
  if (proportional && sx && sy) {
    const requested =
      Math.abs(dw / bounds[2]) > Math.abs(dh / bounds[3])
        ? dw / bounds[2]
        : dh / bounds[3];
    const ratio = Math.max(1 / Math.min(bounds[2], bounds[3]) - 1, requested);
    dw = bounds[2] * ratio;
    dh = bounds[3] * ratio;
  }
  dw = Math.max(1 - bounds[2], dw);
  dh = Math.max(1 - bounds[3], dh);
  return [
    bounds[0] + (c * fx * sx * dw - s * fy * sy * dh - dw) / 2,
    bounds[1] + (s * fx * sx * dw + c * fy * sy * dh - dh) / 2,
    bounds[2] + dw,
    bounds[3] + dh,
  ];
}

// This list describes the preview, not the native writer's larger feature set.
export function previewWarnings(page, deck) {
  const warnings = new Set([
    "浏览器字体、换行和渐变预览尚未通过 PowerPoint 像素对照。",
  ]);
  const inspectFill = (fill) => {
    if (fill?.type === "image")
      warnings.add("图片填充尚未预览；数据保留，原生导出支持部分图片填充。");
    if (fill?.type && !["solid", "gradient", "image"].includes(fill.type))
      warnings.add("存在尚未预览的填充类型。");
  };
  inspectFill(page.background);
  if (page.animations?.length)
    warnings.add("编辑画布为静态；播放模式支持出现、消失和淡入淡出动画。");
  for (const element of page.elements) {
    if (
      !["text", "shape", "image", "line", "chart", "table"].includes(
        element.elementType,
      )
    )
      warnings.add(`${element.elementType} 使用占位框，原始数据保留。`);
    if (element.elementType === "chart")
      warnings.add(
        "图表共享导出器的数据规则；刻度、标签避让、轴标题、边框和曲线预览尚未与 PowerPoint 完全一致。",
      );
    if (element.elementType === "table") {
      warnings.add(
        "表格预览包含合并、样式和单元格文字；公式仍显示源码，字体度量需实机验收。",
      );
      for (const key of ["columnWidths", "rowHeights"]) {
        const values = element[key];
        if (Array.isArray(values) && values.every((v) => typeof v === "number" && v > 0 && v <= 1)) {
          const total = values.reduce((a, b) => a + b, 0);
          if (Math.abs(total - 1) > 1e-6)
            warnings.add(`表格 ${element.elementId} 的 ${key} 合计为 ${(total * 100).toFixed(1)}%；预览与导出按比例适配边界，源数据保留。`);
        }
      }
    }
    if (
      element.elementType === "shape" &&
      !previewShapes.has(element.shapeName)
    )
      warnings.add("部分预设形状使用占位框。");
    if (element.shadow || element.content?.shadow)
      warnings.add("阴影尚未预览。");
    if (element.crop) warnings.add("图片裁剪尚未预览。");
    if (element.content?.gradient) warnings.add("文字渐变尚未预览。");
    if (
      typeof element.content?.text === "string" &&
      element.content.text.includes("\\(")
    )
      warnings.add("公式使用 MathML 预览；字体度量仍需与 PowerPoint 对照。");
    if (
      element.elementType === "line" &&
      String(element.points).trim().split(/\s+/).length !== 2
    )
      warnings.add("复杂线条路径使用占位框。");
    if (["triangle", "diamond"].includes(element.shapeName) && element.border)
      warnings.add("三角形、菱形边框尚未精确预览。");
    if (element.elementType === "text")
      warnings.add(
        "富文本仅预览安全标签及常用样式；其他样式请以 PowerPoint 验收。",
      );
    inspectFill(element.fill);
  }
  return [...warnings];
}

// Check references in every draft and in other theme definitions before removal.
export function themeEntryReferences(theme, pages, kind, name) {
  const needle = "$" + name;
  const contains = (value) => {
    if (typeof value === "string") return value === needle;
    if (!value || typeof value !== "object") return false;
    return Object.values(value).some(contains);
  };
  const references = [];
  pages.forEach((page, index) => {
    if (contains(page)) references.push(`第 ${index + 1} 页`);
  });
  for (const [group, entries] of Object.entries(theme || {})) {
    for (const [key, value] of Object.entries(entries || {})) {
      if (group === kind && key === name) continue;
      if (contains(value)) references.push(`主题 ${group}.${key}`);
    }
  }
  return references;
}
