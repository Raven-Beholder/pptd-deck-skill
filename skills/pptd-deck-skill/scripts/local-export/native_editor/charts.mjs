// Independent SVG preview. Data normalization/validation belongs to Python.
import { color } from "./model.mjs";
const svgNS = "http://www.w3.org/2000/svg";
const sum = (values) =>
  values.reduce((total, value) => total + (value || 0), 0);

export function seriesValues(chart) {
  const bars = chart.series.filter((s) => s.type === "bar");
  return chart.series.map((s) =>
    s.values.map((v, i) =>
      v === null
        ? null
        : s.stack === "percent"
          ? v / (sum(bars.map((b) => b.values[i])) || 1)
          : v,
    ),
  );
}

export function valueRange(chart, values = seriesValues(chart)) {
  const totals = chart.data.rows.map(() => [0, 0]);
  const samples = [0];
  chart.series.forEach((s, j) =>
    values[j].forEach((v, i) => {
      if (v === null) return;
      if (s.type === "bar" && s.stack) totals[i][v >= 0 ? 1 : 0] += v;
      else samples.push(v);
    }),
  );
  samples.push(...totals.flat());
  const axis = chart.horizontal ? chart.xAxis : chart.yAxis;
  let low = axis.min ?? Math.min(...samples),
    high = axis.max ?? Math.max(...samples);
  if (low === high) high = low + 1;
  return [low, high];
}

export function lineSegments(values, handling) {
  const segments = [[]];
  values.forEach((value, index) => {
    if (value === null && handling === "gap") {
      if (segments.at(-1).length) segments.push([]);
    } else if (value !== null || handling === "zero")
      segments.at(-1).push([index, value ?? 0]);
  });
  return segments.filter((s) => s.length);
}

function formatted(value, spec = "General") {
  if (spec.includes("%"))
    return `${(value * 100).toFixed(spec.includes(".0") ? 1 : 0)}%`;
  if (spec === "0.0E+00") return value.toExponential(1);
  if (spec === "#,##0") return Math.round(value).toLocaleString("en-US");
  if (spec === "0.0") return value.toFixed(1);
  if (spec === "0") return String(Math.round(value));
  return Number(value.toPrecision(4)).toString();
}

export function drawChart(chart, theme) {
  const [, , width, height] = chart.bounds;
  const root = document.createElementNS(svgNS, "svg");
  root.setAttribute("viewBox", `0 0 ${width} ${height}`);
  root.style.width = root.style.height = "100%";
  const family = (spec) =>
    typeof spec === "string"
      ? spec
      : [spec?.latin, spec?.ea].filter(Boolean).join(",");
  const measure = document.createElement("canvas").getContext("2d");
  measure.font = `${chart.fontSize}px ${family(chart.fontFamily) || "Arial"}`;
  const make = (tag, attrs = {}, parent = root, text) => {
    const element = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attrs))
      element.setAttribute(key, String(value));
    if (text !== undefined) element.textContent = text;
    parent.append(element);
    return element;
  };
  const defs = make("defs");
  const ink = (paint) => {
    if (typeof paint === "string") return color(paint, theme, "#333333");
    if (paint?.type !== "gradient") return "none";
    const id = `paint-${crypto.randomUUID()}`;
    const gradient = make(
      paint.gradientType === "radial" ? "radialGradient" : "linearGradient",
      { id },
      defs,
    );
    if (paint.gradientType !== "radial") {
      const angle = ((paint.angle || 0) * Math.PI) / 180;
      for (const [key, value] of Object.entries({
        x1: 0.5 - Math.cos(angle) / 2,
        y1: 0.5 - Math.sin(angle) / 2,
        x2: 0.5 + Math.cos(angle) / 2,
        y2: 0.5 + Math.sin(angle) / 2,
      }))
        gradient.setAttribute(key, String(value));
    }
    for (const stop of paint.stops)
      make(
        "stop",
        {
          offset: `${stop.position * 100}%`,
          "stop-color": color(stop.color, theme, "#333333"),
        },
        gradient,
      );
    return `url(#${id})`;
  };
  const border = (spec) => ({
    stroke: spec ? ink(spec.color || "#000000") : "none",
    "stroke-width": spec?.width ?? 1,
    "stroke-dasharray": { dash: "6 4", dot: "1 3" }[spec?.style] || "",
  });
  const label = (x, y, value, spec = {}, attrs = {}) =>
    make(
      "text",
      {
        x,
        y,
        fill: ink(spec.color || "#333333"),
        "font-size": spec.fontSize || chart.fontSize,
        "font-family": family(spec.fontFamily || chart.fontFamily),
        "text-anchor": "middle",
        ...attrs,
      },
      root,
      value,
    );
  make("rect", {
    width,
    height,
    fill:
      chart.fill?.type === "solid" ? ink(chart.fill.color) : ink(chart.fill),
    ...border(chart.border),
  });
  const legend = chart.legend,
    hasLegend = legend.show !== false;
  const topLegend = hasLegend && legend.position === "top";
  const titleHeight = chart.title ? chart.titleFontSize + 12 : 8;
  if (chart.title)
    label(width / 2, chart.titleFontSize + 4, chart.title.text, {
      fontSize: chart.titleFontSize,
      ...chart.title,
    });
  const legendEntries =
    chart.series[0].type === "pie"
      ? chart.series[0].categories.map((name, i) => {
          const s = chart.series[0],
            palette = Array.isArray(s.color)
              ? s.color
              : "fill" in s
                ? [s.color]
                : chart.palette;
          return { name, color: palette[i % palette.length] };
        })
      : chart.series;
  let left = 64,
    right = width - 20,
    top = titleHeight + (topLegend ? 28 : 12),
    bottom = height - (hasLegend && !topLegend ? 56 : 32);
  if (chart.horizontal) {
    const longest = Math.max(
      ...chart.series[0].categories.map(
        (name) => measure.measureText(String(name).slice(0, 256)).width,
      ),
    );
    left = Math.min(width * 0.4, Math.max(left, longest + 16));
  }
  if (hasLegend && ["left", "right"].includes(legend.position)) {
    if (legend.position === "left") left = Math.min(width * 0.35, 140);
    else right -= Math.min(width * 0.3, 120);
    bottom = height - 32;
  }
  if (hasLegend)
    legendEntries.forEach((s, i) => {
      const vertical = ["left", "right"].includes(legend.position);
      const x = vertical
        ? legend.position === "left"
          ? 10
          : right + 12
        : (width * (i + 0.5)) / legendEntries.length - 20;
      const y = vertical
        ? top + i * 24
        : topLegend
          ? titleHeight + 16
          : height - 16;
      make("rect", { x, y: y - 9, width: 10, height: 10, fill: ink(s.color) });
      label(x + 15, y, s.name, legend, { "text-anchor": "start" });
    });
  if (right <= left || bottom <= top) throw new Error("图表太小，无法预览。");
  const pw = right - left,
    ph = bottom - top;
  if (chart.series[0].type === "pie") {
    const s = chart.series[0],
      total = sum(s.values),
      radius = (Math.min(pw, ph) / 2) * 0.9;
    const cx = (left + right) / 2,
      cy = (top + bottom) / 2,
      inner = radius * s.innerRadius;
    const palette = Array.isArray(s.color)
      ? s.color
      : "fill" in s
        ? [s.color]
        : chart.palette;
    let angle = ((s.startAngle - 90) * Math.PI) / 180;
    const point = (r, a) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    s.values.forEach((value, i) => {
      const fraction = (value || 0) / total,
        sweep = fraction * Math.PI * 2,
        end = angle + sweep;
      if (!sweep) return;
      // Two arcs handle a full circle without the SVG coincident-endpoint case.
      const middle = angle + sweep / 2;
      const outer = `M${point(radius, angle)} A${radius},${radius} 0 0 1 ${point(radius, middle)} A${radius},${radius} 0 0 1 ${point(radius, end)}`;
      const path = inner
        ? `${outer} L${point(inner, end)} A${inner},${inner} 0 0 0 ${point(inner, middle)} A${inner},${inner} 0 0 0 ${point(inner, angle)} Z`
        : `${outer} L${cx},${cy} Z`;
      make("path", {
        d: path,
        fill: ink(palette[i % palette.length]),
        ...border(s.border),
      });
      if (s.dataLabels.show) {
        const text =
          s.dataLabels.content === "category"
            ? s.categories[i]
            : s.dataLabels.content === "percentage"
              ? formatted(fraction, s.dataLabels.numberFormat || "0%")
              : formatted(value, s.dataLabels.numberFormat);
        label(
          cx + radius * 0.7 * Math.cos(middle),
          cy + radius * 0.7 * Math.sin(middle),
          text,
          s.dataLabels,
        );
      }
      angle = end;
    });
    return root;
  }
  const values = seriesValues(chart),
    [low, high] = valueRange(chart, values);
  const horizontal = chart.horizontal,
    category = horizontal ? chart.yAxis : chart.xAxis,
    axis = horizontal ? chart.xAxis : chart.yAxis;
  const labels = chart.series[0].categories,
    slot = (horizontal ? ph : pw) / labels.length;
  const cat = (i) =>
    horizontal
      ? category.reverse
        ? top + slot * (i + 0.5)
        : bottom - slot * (i + 0.5)
      : category.reverse
        ? right - slot * (i + 0.5)
        : left + slot * (i + 0.5);
  const value = (v) => {
    let ratio = (v - low) / (high - low);
    if (axis.reverse) ratio = 1 - ratio;
    return horizontal ? left + pw * ratio : bottom - ph * ratio;
  };
  const line = (x1, y1, x2, y2, attrs = {}, parent = root) =>
    make("line", { x1, y1, x2, y2, ...attrs }, parent);
  for (let i = 0; i <= 5; i++) {
    const v = low + ((high - low) * i) / 5,
      p = value(v);
    if (axis.show !== false && axis.gridLine !== false)
      line(
        horizontal ? p : left,
        horizontal ? top : p,
        horizontal ? p : right,
        horizontal ? bottom : p,
        { stroke: "#E2E8F0" },
      );
    if (axis.show !== false && axis.label !== false)
      label(
        horizontal ? p : left - 8,
        horizontal ? bottom + chart.fontSize + 5 : p + chart.fontSize / 3,
        formatted(v, axis.label?.numberFormat || chart.valueFormat),
        typeof axis.label === "object" ? axis.label : {},
        { "text-anchor": horizontal ? "middle" : "end" },
      );
  }
  if (category.show !== false && category.label !== false)
    labels.forEach((name, i) => {
      const spec = typeof category.label === "object" ? category.label : {},
        size = spec.fontSize || chart.fontSize;
      measure.font = `${size}px ${family(spec.fontFamily || chart.fontFamily) || "Arial"}`;
      const available = horizontal ? left - 16 : slot - 8,
        lines = [];
      let text = "";
      for (const char of Array.from(String(name)).slice(0, 256)) {
        if (text && measure.measureText(text + char).width > available) {
          lines.push(text.trim());
          text = "";
          if (lines.length === 2) {
            text = "…";
            break;
          }
        }
        text += char;
      }
      if (text) lines.push(text.trim());
      const x = horizontal ? left - 8 : cat(i),
        y = horizontal
          ? cat(i) + size / 3 - (lines.length - 1) * size * 0.6
          : bottom + size + 5;
      const node = label(x, y, "", spec, {
        "text-anchor": horizontal ? "end" : "middle",
      });
      lines.forEach((line, index) =>
        make("tspan", { x, dy: index ? size * 1.2 : 0 }, node, line),
      );
      make("title", {}, node, name);
    });
  if (category.show !== false && category.axisLine !== false)
    line(left, bottom, right, bottom, { stroke: "#64748B" });
  if (axis.show !== false && axis.axisLine !== false)
    line(left, top, left, bottom, { stroke: "#64748B" });
  const clipId = `plot-${crypto.randomUUID()}`;
  make(
    "rect",
    { x: left, y: top, width: pw, height: ph },
    make("clipPath", { id: clipId }, defs),
  );
  const dataGroup = make("g", { "clip-path": `url(#${clipId})` });
  const bars = chart.series.filter((s) => s.type === "bar"),
    stacked = bars[0]?.stack;
  const starts = labels.map(() => [0, 0]);
  let barIndex = 0;
  chart.series.forEach((s, j) => {
    if (s.type === "bar") {
      const band = slot * chart.barWidth;
      values[j].forEach((v, i) => {
        if (v === null) return;
        const side = v >= 0 ? 1 : 0,
          base = stacked ? starts[i][side] : 0;
        const center =
          cat(i) +
          (stacked
            ? 0
            : (barIndex - (bars.length - 1) / 2) *
              band *
              (1 + (chart.barGap || 0)));
        const p = value(base),
          q = value(base + v);
        make(
          "rect",
          horizontal
            ? {
                x: Math.min(p, q),
                y: center - band / 2,
                width: Math.abs(p - q),
                height: band,
                fill: ink(s.color),
                ...border(s.border),
              }
            : {
                x: center - band / 2,
                y: Math.min(p, q),
                width: band,
                height: Math.abs(p - q),
                fill: ink(s.color),
                ...border(s.border),
              },
          dataGroup,
        );
        starts[i][side] += v;
        if (s.dataLabels.show)
          label(
            horizontal ? q + 5 : center,
            horizontal ? center : q - 5,
            formatted(v, s.dataLabels.numberFormat),
            s.dataLabels,
            { "text-anchor": horizontal ? "start" : "middle" },
          );
      });
      barIndex++;
    } else {
      for (const segment of lineSegments(values[j], chart.nullHandling)) {
        const points = segment.map(([i, v]) => [cat(i), value(v)]);
        make(
          "polyline",
          {
            points: points.map((p) => p.join(",")).join(" "),
            fill: "none",
            stroke: ink(s.color),
            "stroke-width": s.width ?? 2,
            "stroke-dasharray": { dash: "6 4", dot: "1 3" }[s.lineStyle] || "",
          },
          dataGroup,
        );
        points.forEach(([x, y], k) => {
          if (s.marker) {
            const r = (s.marker.size || 6) / 2,
              attrs = {
                fill: ink(s.marker.fill || s.color),
                ...border(s.marker.border),
              };
            const shape = s.marker.shape || "circle";
            if (shape === "circle")
              make("circle", { cx: x, cy: y, r, ...attrs }, dataGroup);
            else if (shape === "rect")
              make(
                "rect",
                { x: x - r, y: y - r, width: r * 2, height: r * 2, ...attrs },
                dataGroup,
              );
            else
              make(
                "polygon",
                {
                  points:
                    shape === "triangle"
                      ? `${x},${y - r} ${x + r},${y + r} ${x - r},${y + r}`
                      : `${x},${y - r} ${x + r},${y} ${x},${y + r} ${x - r},${y}`,
                  ...attrs,
                },
                dataGroup,
              );
          }
          if (s.dataLabels.show)
            label(
              x,
              y - 7,
              formatted(segment[k][1], s.dataLabels.numberFormat),
              s.dataLabels,
            );
        });
      }
    }
  });
  return root;
}
