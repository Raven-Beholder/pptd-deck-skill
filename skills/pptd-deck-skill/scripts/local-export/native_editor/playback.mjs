// Browser player for the native exporter's validated click-group schedule.
// Visibility snapshots make previous/next deterministic even mid-animation.
export class Playback {
  constructor(groups, boxes) {
    this.groups = groups;
    this.boxes = boxes;
    this.position = 0;
    this.snapshots = [];
    this.timers = [];
    this.animations = [];
    this.base = new Map(
      [...boxes].map(([id, box]) => [id, box.style.opacity || "1"]),
    );
    const first = new Set();
    for (const group of groups)
      for (const event of group.events) {
        if (first.has(event.shape_id)) continue;
        first.add(event.shape_id);
        if (["appear", "fade-in"].includes(event.effect))
          boxes.get(event.shape_id).style.visibility = "hidden";
      }
  }
  snapshot() {
    return [...this.boxes].map(([id, box]) => [
      id,
      box.style.visibility,
      box.style.opacity,
    ]);
  }
  cancel() {
    for (const timer of this.timers) clearTimeout(timer);
    this.timers = [];
    for (const animation of this.animations) animation.cancel();
    this.animations = [];
  }
  apply(event) {
    const box = this.boxes.get(event.shape_id);
    box.style.visibility = ["appear", "fade-in"].includes(event.effect)
      ? "visible"
      : "hidden";
    box.style.opacity = this.base.get(event.shape_id);
  }
  finish() {
    this.cancel();
    if (this.position)
      for (const event of this.groups[this.position - 1].events)
        this.apply(event);
  }
  run() {
    if (this.position >= this.groups.length) return false;
    this.finish();
    this.snapshots.push(this.snapshot());
    const group = this.groups[this.position++];
    for (const event of group.events) {
      const timer = setTimeout(() => {
        const box = this.boxes.get(event.shape_id),
          entrance = ["appear", "fade-in"].includes(event.effect);
        box.style.visibility = "visible";
        if (event.effect.startsWith("fade")) {
          const opacity = Number(this.base.get(event.shape_id));
          const animation = box.animate(
            [
              { opacity: entrance ? 0 : opacity },
              { opacity: entrance ? opacity : 0 },
            ],
            { duration: event.duration, fill: "forwards", easing: "linear" },
          );
          this.animations.push(animation);
          animation.finished
            .then(() => {
              this.apply(event);
              animation.cancel();
            })
            .catch(() => {});
        } else this.apply(event);
      }, event.start);
      this.timers.push(timer);
    }
    return true;
  }
  start() {
    if (this.groups[0] && !this.groups[0].click) this.run();
  }
  next() {
    return this.run();
  }
  previous() {
    if (this.position === 0) return false;
    this.cancel();
    this.position--;
    const previous = this.snapshots.pop();
    for (const [id, visibility, opacity] of previous) {
      const box = this.boxes.get(id);
      box.style.visibility = visibility;
      box.style.opacity = opacity;
    }
    return true;
  }
  dispose() {
    this.cancel();
  }
}
