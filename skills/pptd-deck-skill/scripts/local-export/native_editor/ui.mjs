// Native UI behavior and independently drawn toolbar icons.
import { ICONS } from "./icons.mjs";

const aliases = {
  shapes: "Shape",
  text: "Text",
  image: "Image",
  table: "Tabular",
  theme: "Style",
  plus: "plus",
  undo: "Undo",
  redo: "Redo",
  pages: "Pages",
  play: "Play",
  fullscreen: "Expand",
  trash: "Delete",
  layers: "Layer",
  opacity: "Alpha",
  flipH: "Flip",
  flipV: "Flip_b",
  replace: "Replace",
  align: "LeftAlign",
  anchor: "TopAlign",
  spacing: "LineSpace",
  more: "More",
  chevron: "Down_b",
};
export function icon(name) {
  const data = ICONS[aliases[name] || name];
  if (!data) throw new Error(`Unknown UI icon: ${name}`);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", data.viewBox);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("class", "ui-icon");
  svg.setAttribute("data-native-icon", aliases[name] || name);
  for (const { tag, attrs } of data.children) {
    const child = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attrs))
      child.setAttribute(key, value);
    svg.append(child);
  }
  return svg;
}
export function setButtonIcon(id, name, dropdown = false) {
  const target = document.getElementById(id);
  if (!target) return;
  target.replaceChildren(icon(name));
  target.classList.toggle("icon-dropdown", dropdown);
  if (dropdown) {
    const caret = icon("Down_b");
    caret.classList.add("icon-caret");
    target.append(caret);
  }
}
export function installIcons() {
  for (const [id, name, dropdown] of [
    ["add-shape", "shapes"],
    ["add-text", "text"],
    ["add-image", "image"],
    ["add-table", "table"],
    ["open-theme", "theme"],
    ["more-insert", "more"],
    ["undo", "undo"],
    ["redo", "redo"],
    ["toggle-pages", "pages"],
    ["preview-deck", "play"],
    ["editor-fullscreen", "fullscreen"],
    ["delete-selection", "trash"],
    ["zoom-in", "plus"],
    ["zoom-out", "minus"],
    ["text-opacity", "opacity"],
    ["text-layer", "layers", true],
    ["shape-opacity", "opacity"],
    ["shape-layer", "layers", true],
    ["shape-flip-h", "flipH"],
    ["shape-flip-v", "flipV"],
    ["shape-replace", "replace", true],
    ["text-expand", "Right_b"],
    ["text-more", "Right_b"],
    ["text-horizontal", "align", true],
    ["text-vertical", "anchor", true],
    ["text-spacing", "spacing", true],
    ["text-bold", "Bold"],
    ["text-italic", "Italic"],
    ["text-underline", "Underline"],
    ["text-strike", "StrikeThrough"],
    ["text-fx", "MathFormula", true],
  ])
    setButtonIcon(id, name, dropdown);
  for (const [id, name, label] of [
    ["new-page", "CirclePlus", "新建页面"],
    ["shape-tab", "Shape", "形状"],
    ["line-tab", "Line", "线条"],
    ["icon-tab", "Icon", "图标"],
    ["insert-formula", "MathFormula", "插入公式"],
    ["insert-watermark", "Watermark", "添加水印"],
    ["export", "Output", "导出"],
  ]) {
    const target = document.getElementById(id);
    if (target)
      target.replaceChildren(icon(name), document.createTextNode(label));
  }
  for (const [id, name] of [
    ["text-color", "FontColor"],
    ["text-highlight", "FontHighlight"],
  ])
    document.getElementById(id).nextElementSibling.replaceChildren(icon(name));
  const fillOptions = document.getElementById("shape-fill-options");
  fillOptions.replaceChildren(document.createTextNode("填充"), icon("Down_b"));
  fillOptions.lastElementChild.classList.add("icon-caret");
}
export class Popup {
  constructor(run) {
    this.run = run;
    this.node = document.createElement("div");
    this.node.className = "context-menu";
    this.node.role = "menu";
    this.node.hidden = true;
    document.body.append(this.node);
    document.addEventListener("pointerdown", (event) => {
      if (!this.node.contains(event.target)) this.close();
    });
    document.addEventListener("keydown", (event) => {
      if (this.node.hidden) return;
      if (event.key === "Escape") {
        event.preventDefault();
        this.close();
        this.origin?.focus();
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const buttons = [
          ...this.node.querySelectorAll("button:not(:disabled)"),
        ];
        let index = buttons.indexOf(document.activeElement);
        index =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? buttons.length - 1
              : (index +
                  (event.key === "ArrowDown" ? 1 : -1) +
                  buttons.length) %
                buttons.length;
        buttons[index]?.focus();
      }
    });
  }
  close() {
    this.node.hidden = true;
  }
  show(entries, x, y, origin = document.activeElement) {
    this.origin = origin;
    this.node.dataset.controlOwner = origin?.id || "";
    this.node.replaceChildren();
    for (const entry of entries) {
      if (!entry) {
        this.node.append(document.createElement("hr"));
        continue;
      }
      const button = document.createElement("button");
      button.role = "menuitem";
      button.disabled = Boolean(entry.disabled);
      const label = document.createElement("span");
      label.textContent = entry.label;
      button.append(label);
      if (entry.hint) {
        const hint = document.createElement("kbd");
        hint.textContent = entry.hint;
        button.append(hint);
      }
      button.addEventListener("click", () => {
        this.close();
        this.run(entry.action);
      });
      this.node.append(button);
    }
    this.node.hidden = false;
    const rect = this.node.getBoundingClientRect();
    this.node.style.left = `${Math.max(8, Math.min(x, innerWidth - rect.width - 8))}px`;
    this.node.style.top = `${Math.max(8, Math.min(y, innerHeight - rect.height - 8))}px`;
    this.node.querySelector("button:not(:disabled)")?.focus();
  }
  below(button, entries) {
    const rect = button.getBoundingClientRect();
    this.show(entries, rect.left, rect.bottom + 8, button);
  }
}

// Shared listbox for selects and searchable local-font previews. Native selects
// remain the value/event source; the visible control has consistent styling.
export function enhanceControls() {
  const controls = [];
  let opened;
  const close = () => {
    if (!opened) return;
    opened.panel.remove();
    opened.trigger.setAttribute("aria-expanded", "false");
    opened.trigger.removeAttribute("aria-activedescendant");
    opened = null;
  };
  const open = (control, filter = "") => {
    close();
    const { source, trigger, font } = control;
    const panel = document.createElement("div");
    panel.className = `choice-popup${font ? " font-popup" : ""}`;
    panel.id = `${source.id}-choices`;
    panel.role = "listbox";
    panel.setAttribute("aria-label", trigger.getAttribute("aria-label"));
    panel.dataset.controlOwner = source.id;
    const options = font
      ? [...document.getElementById("font-families").options]
          .filter((o) =>
            o.value.toLocaleLowerCase().includes(filter.toLocaleLowerCase()),
          )
          .slice(0, 100)
      : [...source.options];
    const choose = (option) => {
      source.value = option.value;
      close();
      source.dispatchEvent(new Event("change", { bubbles: true }));
      sync();
    };
    for (const [index, option] of options.entries()) {
      const row = document.createElement("button");
      row.type = "button";
      row.role = "option";
      row.id = `${source.id}-choice-${index}`;
      row.tabIndex = -1;
      row.disabled = option.disabled;
      row.setAttribute("aria-selected", String(option.value === source.value));
      const label = document.createElement("span");
      label.textContent = option.label || option.value;
      label.title = label.textContent;
      row.append(label);
      if (font) {
        label.style.fontFamily = JSON.stringify(option.value);
        const sample = document.createElement("span");
        sample.className = "font-sample";
        sample.style.fontFamily = JSON.stringify(option.value);
        sample.textContent = "Aa 文字 123";
        row.append(sample);
      } else if (option.value === source.value) {
        const check = document.createElement("span");
        check.className = "choice-check";
        check.textContent = "✓";
        row.append(check);
      }
      row.addEventListener("pointerdown", (e) => e.preventDefault());
      row.addEventListener("click", () => choose(option));
      panel.append(row);
    }
    if (font && options.length) {
      const note = document.createElement("p");
      note.className = "font-preview-note";
      note.textContent = "本机字体预览 · 缺失字形由系统回退";
      panel.append(note);
    }
    if (!options.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "未找到本地字体，可输入名称后按 Enter。";
      panel.append(empty);
    }
    (source.closest("dialog") || document.body).append(panel);
    const rect = trigger.getBoundingClientRect();
    panel.style.width = `${Math.min(innerWidth - 24, Math.max(rect.width, font ? 340 : 160))}px`;
    panel.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - panel.offsetWidth - 12))}px`;
    const below = innerHeight - rect.bottom - 12;
    const above = rect.top - 12;
    const height = Math.min(340, Math.max(below, above));
    panel.style.maxHeight = `${height}px`;
    panel.style.top = `${below >= Math.min(240, panel.scrollHeight) || below >= above ? rect.bottom + 6 : Math.max(12, rect.top - Math.min(panel.scrollHeight, height) - 6)}px`;
    opened = { ...control, panel, index: -1 };
    trigger.setAttribute("aria-expanded", "true");
    trigger.setAttribute("aria-controls", panel.id);
  };
  const keydown = (e, control) => {
    if (e.isComposing) return;
    if (e.key === "Escape") {
      if (opened) {
        e.preventDefault();
        e.stopPropagation();
        close();
      }
      return;
    }
    if (e.key === "Tab") {
      close();
      return;
    }
    if (
      ["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) &&
      (opened || e.key.startsWith("Arrow"))
    ) {
      e.preventDefault();
      e.stopPropagation();
      if (opened?.source !== control.source) open(control);
      const rows = [...opened.panel.querySelectorAll("button:not(:disabled)")];
      if (!rows.length) return;
      opened.index =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? rows.length - 1
            : (opened.index + (e.key === "ArrowUp" ? -1 : 1) + rows.length) %
              rows.length;
      rows.forEach((row, i) =>
        row.classList.toggle("keyboard-active", i === opened.index),
      );
      const active = rows[opened.index];
      control.trigger.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" || (!control.font && e.key === " ")) {
      e.preventDefault();
      e.stopPropagation();
      if (opened?.source === control.source && opened.index >= 0)
        opened.panel
          .querySelectorAll("button:not(:disabled)")
          [opened.index]?.click();
      else if (control.font) {
        close();
        control.source.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (opened) close();
      else open(control);
    }
  };
  for (const source of document.querySelectorAll(
    "select,input[list='font-families']",
  )) {
    const font = source.tagName === "INPUT";
    let trigger = source;
    if (!font) {
      const wrapper = document.createElement("span");
      wrapper.className = "select-control";
      wrapper.dataset.controlOwner = source.id;
      source.before(wrapper);
      wrapper.append(source);
      source.hidden = true;
      trigger = document.createElement("button");
      trigger.id = `${source.id}-trigger`;
      trigger.type = "button";
      trigger.className = "select-trigger";
      trigger.setAttribute(
        "aria-label",
        source.getAttribute("aria-label") ||
          source.closest("label")?.textContent.trim().split("\n")[0] ||
          source.id,
      );
      const value = document.createElement("span");
      value.className = "select-value";
      trigger.append(value, icon("Down_b"));
      wrapper.append(trigger);
    } else {
      source.removeAttribute("list");
      source.setAttribute("aria-autocomplete", "list");
    }
    trigger.role = "combobox";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    const control = { source, trigger, font };
    controls.push(control);
    trigger.addEventListener("click", () =>
      opened?.source === source && !font ? close() : open(control),
    );
    trigger.addEventListener("keydown", (e) => keydown(e, control));
    if (font)
      source.addEventListener("input", () => open(control, source.value));
    source.addEventListener("change", () => {
      close();
      sync();
    });
    if (!font)
      new MutationObserver(() => sync()).observe(source, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true,
      });
  }
  function sync() {
    for (const { source, trigger, font } of controls) {
      if (font)
        trigger.style.fontFamily = source.value
          ? JSON.stringify(source.value)
          : "";
      else {
        trigger.querySelector(".select-value").textContent =
          source.selectedOptions[0]?.label || "请选择";
        trigger.disabled = source.matches(":disabled");
      }
    }
  }
  document.addEventListener("pointerdown", (e) => {
    if (
      opened &&
      !opened.panel.contains(e.target) &&
      !opened.trigger.contains(e.target)
    )
      close();
  });
  document.addEventListener("focusin", (e) => {
    if (
      opened &&
      !opened.panel.contains(e.target) &&
      e.target !== opened.trigger
    )
      close();
  });
  window.addEventListener("resize", close);
  document.addEventListener(
    "scroll",
    (e) => {
      if (opened && !opened.panel.contains(e.target)) close();
    },
    true,
  );
  sync();
  return { sync, close };
}
