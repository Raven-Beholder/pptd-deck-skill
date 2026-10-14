// Original geometric previews. No vendor icon/font assets are used.
export const SHAPES = [
  ["rect", "矩形", "矩形"],
  ["roundRect", "圆角矩形", "矩形"],
  ["ellipse", "椭圆", "基础形状"],
  ["triangle", "三角形", "基础形状"],
  ["diamond", "菱形", "基础形状"],
  ["parallelogram", "平行四边形", "基础形状"],
  ["trapezoid", "梯形", "基础形状"],
  ["pentagon", "五边形", "基础形状"],
  ["hexagon", "六边形", "基础形状"],
  ["octagon", "八边形", "基础形状"],
  ["chevron", "燕尾箭头", "箭头"],
  ["homePlate", "五角箭头", "箭头"],
  ["rightArrow", "向右箭头", "箭头"],
  ["leftArrow", "向左箭头", "箭头"],
  ["upArrow", "向上箭头", "箭头"],
  ["downArrow", "向下箭头", "箭头"],
  ["star5", "五角星", "装饰"],
  ["donut", "圆环", "装饰"],
];
// Additional preset names follow the public DrawingML shape enumeration.
SHAPES.push(
  ["round1Rect", "单圆角矩形", "矩形"],
  ["round2SameRect", "同侧圆角矩形", "矩形"],
  ["round2DiagRect", "对角圆角矩形", "矩形"],
  ["snip1Rect", "单切角矩形", "矩形"],
  ["snip2SameRect", "同侧切角矩形", "矩形"],
  ["snip2DiagRect", "对角切角矩形", "矩形"],
  ["snipRoundRect", "切角圆角矩形", "矩形"],
  ["rtTriangle", "直角三角形", "基础形状"],
  ["heptagon", "七边形", "基础形状"],
  ["decagon", "十边形", "基础形状"],
  ["dodecagon", "十二边形", "基础形状"],
  ["plus", "十字形", "基础形状"],
  ["leftRightArrow", "左右箭头", "箭头"],
  ["upDownArrow", "上下箭头", "箭头"],
  ["star4", "四角星", "装饰"],
  ["star6", "六角星", "装饰"],
  ["star8", "八角星", "装饰"],
  ["heart", "心形", "装饰"],
);
SHAPES.sort(
  (a, b) =>
    ["矩形", "基础形状", "箭头", "装饰"].indexOf(a[2]) -
    ["矩形", "基础形状", "箭头", "装饰"].indexOf(b[2]),
);
const PATHS = {
  triangle: "M50 0 100 100 0 100Z",
  diamond: "M50 0 100 50 50 100 0 50Z",
  parallelogram: "M25 0 100 0 75 100 0 100Z",
  trapezoid: "M25 0 75 0 100 100 0 100Z",
  pentagon: "M50 0 100 38 81 100 19 100 0 38Z",
  hexagon: "M25 0 75 0 100 50 75 100 25 100 0 50Z",
  octagon: "M29 0 71 0 100 29 100 71 71 100 29 100 0 71 0 29Z",
  chevron: "M0 0 50 0 100 50 50 100 0 100 50 50Z",
  homePlate: "M0 0 50 0 100 50 50 100 0 100Z",
  rightArrow: "M0 25 50 25 50 0 100 50 50 100 50 75 0 75Z",
  leftArrow: "M100 25 50 25 50 0 0 50 50 100 50 75 100 75Z",
  upArrow: "M25 100 25 50 0 50 50 0 100 50 75 50 75 100Z",
  downArrow: "M25 0 25 50 0 50 50 100 100 50 75 50 75 0Z",
  star5: "M50 0 62 35 100 35 69 58 81 95 50 72 19 95 31 58 0 35 38 35Z",
  donut: "M50 0A50 50 0 1 1 49.99 0ZM50 25A25 25 0 1 0 50.01 25Z",
};
Object.assign(PATHS, {
  round1Rect: "M0 0H84Q100 0 100 16V100H0Z",
  round2SameRect: "M16 0H84Q100 0 100 16V100H0V16Q0 0 16 0Z",
  round2DiagRect: "M0 0H84Q100 0 100 16V100H16Q0 100 0 84Z",
  snip1Rect: "M0 0H84L100 16V100H0Z",
  snip2SameRect: "M16 0H84L100 16V100H0V16Z",
  snip2DiagRect: "M0 0H84L100 16V100H16L0 84Z",
  snipRoundRect: "M16 0H84L100 16V100H0V16Q0 0 16 0Z",
  rtTriangle: "M0 0 100 100 0 100Z",
  plus: "M33 0H67V33H100V67H67V100H33V67H0V33H33Z",
  leftRightArrow: "M0 50 25 0V25H75V0L100 50 75 100V75H25V100Z",
  upDownArrow: "M50 0 100 25H75V75H100L50 100 0 75H25V25H0Z",
  heart:
    "M50 100C25 80 0 55 0 25C0-5 40-8 50 20C60-8 100-5 100 25C100 55 75 80 50 100Z",
});
for (const [name, count] of [
  ["heptagon", 7],
  ["decagon", 10],
  ["dodecagon", 12],
  ["star4", 4],
  ["star6", 6],
  ["star8", 8],
]) {
  const star = name.startsWith("star"),
    vertices = star ? count * 2 : count;
  PATHS[name] =
    Array.from({ length: vertices }, (_, i) => {
      const radius = star && i % 2 ? 22 : 50,
        angle = (i * 2 * Math.PI) / vertices - Math.PI / 2;
      return `${i ? "L" : "M"}${50 + radius * Math.cos(angle)} ${50 + radius * Math.sin(angle)}`;
    }).join("") + "Z";
}
const NS = "http://www.w3.org/2000/svg";
let nextId = 0;
function node(tag, attributes = {}) {
  const element = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attributes))
    element.setAttribute(key, String(value));
  return element;
}
export function drawShape(item, resolveColor) {
  const svg = node("svg", {
    viewBox: "0 0 100 100",
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  Object.assign(svg.style, {
    width: "100%",
    height: "100%",
    overflow: "visible",
  });
  let geometry;
  if (item.shapeName === "ellipse")
    geometry = node("ellipse", { cx: 50, cy: 50, rx: 50, ry: 50 });
  else if (["rect", "roundRect"].includes(item.shapeName))
    geometry = node("rect", {
      width: 100,
      height: 100,
      rx: item.shapeName === "roundRect" ? 12 : 0,
    });
  else if (PATHS[item.shapeName])
    geometry = node("path", {
      d: PATHS[item.shapeName],
      "fill-rule": "evenodd",
    });
  else throw new Error(`未支持的图形：${item.shapeName}`);
  const fill = item.fill;
  geometry.setAttribute(
    "fill",
    fill?.type === "solid" ? resolveColor(fill.color) : "none",
  );
  if (fill?.type === "gradient") {
    const id = `shape-gradient-${++nextId}`,
      radial = fill.gradientType === "radial";
    const angle = ((Number(fill.angle || 0) + 90) * Math.PI) / 180;
    const gradient = node(
      radial ? "radialGradient" : "linearGradient",
      radial
        ? { id }
        : {
            id,
            x1: `${50 - Math.cos(angle) * 50}%`,
            y1: `${50 - Math.sin(angle) * 50}%`,
            x2: `${50 + Math.cos(angle) * 50}%`,
            y2: `${50 + Math.sin(angle) * 50}%`,
          },
    );
    for (const stop of fill.stops || [])
      gradient.append(
        node("stop", {
          offset: `${stop.position * 100}%`,
          "stop-color": resolveColor(stop.color),
        }),
      );
    const defs = node("defs");
    defs.append(gradient);
    svg.append(defs);
    geometry.setAttribute("fill", `url(#${id})`);
  }
  if (item.border) {
    geometry.setAttribute("stroke", resolveColor(item.border.color));
    geometry.setAttribute("stroke-width", item.border.width ?? 1);
    geometry.setAttribute("vector-effect", "non-scaling-stroke");
    if (item.border.style !== "solid")
      geometry.setAttribute(
        "stroke-dasharray",
        item.border.style === "dot" ? "1 3" : "6 4",
      );
  }
  svg.append(geometry);
  return svg;
}
export function drawLine(item, resolveColor) {
  const size = item.viewBox,
    points = String(item.points)
      .trim()
      .split(/\s+/)
      .map((p) => p.split(",").map(Number));
  if (
    !Array.isArray(size) ||
    size.length !== 2 ||
    points.length !== 2 ||
    points.some((p) => p.length !== 2 || p.some((n) => !Number.isFinite(n)))
  )
    throw new Error("当前预览支持两点直线。");
  const svg = node("svg", {
    viewBox: `0 0 ${size.join(" ")}`,
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  Object.assign(svg.style, {
    width: "100%",
    height: "100%",
    overflow: "visible",
  });
  const line = node("line", {
    x1: points[0][0],
    y1: points[0][1],
    x2: points[1][0],
    y2: points[1][1],
    stroke: resolveColor(item.border?.color || "#172554"),
    "stroke-width": item.border?.width ?? 2,
    "vector-effect": "non-scaling-stroke",
  });
  if (item.border?.style === "dash")
    line.setAttribute("stroke-dasharray", "6 4");
  if (item.border?.style === "dot")
    line.setAttribute("stroke-dasharray", "1 3");
  (item.arrow || []).forEach((kind, index) => {
    if (!kind) return;
    const id = `line-arrow-${++nextId}`,
      marker = node("marker", {
        id,
        viewBox: "0 0 10 10",
        refX: 9,
        refY: 5,
        markerWidth: 6,
        markerHeight: 6,
        orient: "auto-start-reverse",
      });
    const path =
      kind === "oval"
        ? node("circle", { cx: 5, cy: 5, r: 4 })
        : node("path", {
            d:
              kind === "diamond"
                ? "M0 5 5 0 10 5 5 10Z"
                : kind === "stealth"
                  ? "M0 0 10 5 0 10 3 5Z"
                  : "M0 0 10 5 0 10Z",
          });
    path.setAttribute("fill", resolveColor(item.border?.color || "#172554"));
    marker.append(path);
    const defs = node("defs");
    defs.append(marker);
    svg.append(defs);
    line.setAttribute(index ? "marker-end" : "marker-start", `url(#${id})`);
  });
  svg.append(line);
  return svg;
}
