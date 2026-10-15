// Page sorting keeps the manifest unchanged until a completed drop.
export function pageDropIndex(from, y, rows) {
  return rows.filter((row, index) => index !== from && y >= (row.top + row.bottom) / 2).length;
}

export function pageScrollSpeed(y, top, bottom) {
  const edge = Math.min(56, (bottom - top) / 4);
  if (edge <= 0) return 0;
  if (y < top + edge) return -18 * Math.min(1, (top + edge - y) / edge);
  if (y > bottom - edge) return 18 * Math.min(1, (y - bottom + edge) / edge);
  return 0;
}

export class PageDrag {
  constructor(root, viewport, { canStart, onDrop }) {
    this.root = root;
    this.viewport = viewport;
    this.canStart = canStart;
    this.onDrop = onDrop;
    root.addEventListener("pointerdown", (event) => this.begin(event));
    root.addEventListener("click", (event) => {
      if (!this.suppressClick) return;
      this.suppressClick = false;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
    window.addEventListener("pointermove", (event) => this.move(event));
    window.addEventListener("pointerup", (event) => this.finish(event));
    window.addEventListener("pointercancel", () => this.cancel());
    window.addEventListener("blur", () => this.cancel());
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.state) {
        event.preventDefault();
        this.cancel();
      }
    });
  }
  begin(event) {
    this.suppressClick = false;
    const source = event.target.closest("button[data-page]");
    if (event.button !== 0 || !source || !this.canStart()) return;
    const bounds = source.getBoundingClientRect();
    this.state = {
      source, pointerId: event.pointerId, from: Number(source.dataset.page),
      startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY,
      offsetX: event.clientX - bounds.left, offsetY: event.clientY - bounds.top,
    };
    source.setPointerCapture(event.pointerId);
  }
  move(event) {
    const state = this.state;
    if (!state || state.pointerId !== event.pointerId) return;
    state.x = event.clientX;
    state.y = event.clientY;
    if (!state.ghost) {
      if (Math.hypot(state.x - state.startX, state.y - state.startY) < 6) return;
      this.start();
    }
    event.preventDefault();
    this.update();
  }
  start() {
    const state = this.state, rootTop = this.root.getBoundingClientRect().top;
    state.buttons = [...this.root.querySelectorAll("button[data-page]")];
    state.rows = state.buttons.map((button) => {
      const bounds = button.getBoundingClientRect();
      return { top: bounds.top - rootTop, bottom: bounds.bottom - rootTop };
    });
    const bounds = state.source.getBoundingClientRect();
    state.height = bounds.height;
    state.stride = state.height + parseFloat(getComputedStyle(this.root).gap || "0");
    state.ghost = state.source.cloneNode(true);
    state.ghost.className = "page-drag-ghost";
    state.ghost.removeAttribute("data-page");
    state.ghost.setAttribute("aria-hidden", "true");
    Object.assign(state.ghost.style, { width: `${bounds.width}px`, height: `${bounds.height}px` });
    document.body.append(state.ghost);
    state.slot = document.createElement("div");
    state.slot.className = "page-drop-slot";
    state.slot.setAttribute("aria-hidden", "true");
    state.slot.style.height = `${state.height}px`;
    this.root.append(state.slot);
    state.source.classList.add("page-drag-source");
    state.buttons.forEach((button) => button.classList.add("page-drag-shift"));
    document.body.classList.add("is-page-dragging");
    this.frame = requestAnimationFrame((time) => this.scroll(time));
  }
  bounds() {
    const bounds = this.viewport.getBoundingClientRect();
    const footer = this.viewport.querySelector(".new-page")?.getBoundingClientRect();
    return { left: bounds.left, right: bounds.right, top: bounds.top,
      bottom: footer ? Math.min(bounds.bottom, footer.top) : bounds.bottom };
  }
  update() {
    const state = this.state;
    if (!state?.ghost) return;
    Object.assign(state.ghost.style, {
      left: `${state.x - state.offsetX}px`, top: `${state.y - state.offsetY}px`,
    });
    const bounds = this.bounds();
    state.inside = state.x >= bounds.left && state.x <= bounds.right;
    state.slot.hidden = !state.inside;
    const y = state.y - this.root.getBoundingClientRect().top;
    state.to = pageDropIndex(state.from, y, state.rows);
    state.buttons.forEach((button, index) => {
      const offset = state.to > state.from && index > state.from && index <= state.to
        ? -state.stride : state.to < state.from && index >= state.to && index < state.from
          ? state.stride : 0;
      button.style.transform = offset ? `translateY(${offset}px)` : "";
    });
    const row = state.rows[state.to];
    state.slot.style.top = `${state.to > state.from ? row.bottom - state.height : row.top}px`;
    state.slot.textContent = `移到第 ${state.to + 1} 页`;
  }
  scroll(time) {
    const state = this.state;
    if (!state?.ghost) return;
    const bounds = this.bounds(), elapsed = Math.min(32, time - (state.time ?? time - 16));
    state.time = time;
    if (state.inside) {
      this.viewport.scrollTop += pageScrollSpeed(state.y, bounds.top, bounds.bottom) * elapsed / 16;
      this.update();
    }
    this.frame = requestAnimationFrame((next) => this.scroll(next));
  }
  finish(event) {
    const state = this.state;
    if (!state || state.pointerId !== event.pointerId) return;
    state.x = event.clientX;
    state.y = event.clientY;
    this.update();
    const bounds = this.bounds();
    const dropped = state.ghost && state.inside && state.y >= bounds.top && state.y <= bounds.bottom;
    const from = state.from, to = state.to;
    this.cancel();
    if (dropped && from !== to) this.onDrop(from, to);
  }
  cancel() {
    const state = this.state;
    if (!state) return;
    this.suppressClick = Boolean(state.ghost);
    cancelAnimationFrame(this.frame);
    state.ghost?.remove();
    state.slot?.remove();
    state.source.classList.remove("page-drag-source");
    state.buttons?.forEach((button) => {
      button.classList.remove("page-drag-shift");
      button.style.transform = "";
    });
    if (state.source.hasPointerCapture(state.pointerId)) state.source.releasePointerCapture(state.pointerId);
    document.body.classList.remove("is-page-dragging");
    this.state = null;
  }
}
