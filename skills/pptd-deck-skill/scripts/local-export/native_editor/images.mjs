// Original slide image serialization. Uses the editor render tree and no third-party rasterizer.
export async function slideImage(
  project,
  record,
  { paint, drawElement, complexPreview, previewFor, api, formulaCache, fontCSS = "" },
) {
  await document.fonts.ready;
  const [w, h] = project.deck.size,
    host = document.createElement("div");
  host.className = "image-export-surface";
  Object.assign(host.style, {
    position: "fixed",
    left: "-20000px",
    top: "0",
    width: `${w}px`,
    height: `${h}px`,
  });
  document.body.append(host);
  try {
    const background = record.page.background || {
      type: "solid",
      color: "#FFFFFF",
    };
    paint(
      host,
      background.type === "image"
        ? { type: "solid", color: "#FFFFFF" }
        : background,
    );
    for (const item of record.page.elements)
      host.append(drawElement(item, false));
    const result = await previewFor(record);
    for (const box of host.children)
      if (result.elements[box.dataset.id])
        complexPreview(box, result.elements[box.dataset.id]);
    if (record.page.background?.type === "image") {
      const blob = await api(
        `/api/image?path=${encodeURIComponent(record.page.background.src)}`,
        undefined,
        true,
      );
      host.style.backgroundImage = `url(${await dataURL(blob)})`;
      host.style.backgroundSize =
        { contain: "contain", cover: "cover", fill: "100% 100%" }[
          background.fit?.mode
        ] || "cover";
      host.style.backgroundPosition = "center";
      host.style.backgroundRepeat = "no-repeat";
    }
    for (const image of host.querySelectorAll("img")) {
      const data = await api(
        `/api/image?path=${encodeURIComponent(image.alt)}`,
        undefined,
        true,
      );
      image.src = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(data);
      });
    }
    await Promise.all([...formulaCache.values()]);
    if (
      Object.values(result.elements).some((e) => e.error) ||
      host.querySelector(".placeholder")
    )
      throw new Error("当前页包含无法预览的元素，图片导出已停止。");
    const cloneHost = host.cloneNode(true),
      originals = [host, ...host.querySelectorAll("*")],
      copies = [cloneHost, ...cloneHost.querySelectorAll("*")];
    originals.forEach((node, index) => {
      const css = getComputedStyle(node);
      copies[index].setAttribute(
        "style",
        imageStyleKeys
          .map((key) => `${key}:${css.getPropertyValue(key)}`)
          .join(";"),
      );
      if (node.namespaceURI === "http://www.w3.org/1999/xhtml")
        copies[index].removeAttribute("id");
    });
    Object.assign(cloneHost.style, {
      position: "relative",
      left: "0",
      top: "0",
      margin: "0",
    });
    cloneHost.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
    if (fontCSS) {
      const style = document.createElement("style");
      style.textContent = fontCSS;
      cloneHost.prepend(style);
    }
    const source = new XMLSerializer().serializeToString(cloneHost);
    return new Blob(
      [
        `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><foreignObject width="100%" height="100%">${source}</foreignObject></svg>`,
      ],
      { type: "image/svg+xml" },
    );
  } finally {
    host.remove();
  }
}

export async function rasterImage(svg, size) {
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(svg);
  });
  const image = new Image();
  image.src = data;
  try {
    await image.decode();
  } catch {
    throw new Error("此浏览器无法读取 SVG 画面，请选择 SVG 图片格式。");
  }
  const canvas = document.createElement("canvas");
  const factor = Math.min(
    2,
    4096 / Math.max(...size),
    Math.sqrt(16_000_000 / (size[0] * size[1])),
  );
  canvas.width = Math.ceil(size[0] * factor);
  canvas.height = Math.ceil(size[1] * factor);
  canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
  try {
    return await new Promise((resolve, reject) =>
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("图片编码失败。"))),
        "image/png",
      ),
    );
  } catch {
    throw new Error("此浏览器无法将幻灯片转换为 PNG，请选择 SVG 图片格式。");
  }
}

const imageStyleKeys = [
  "position",
  "left",
  "right",
  "top",
  "bottom",
  "width",
  "height",
  "min-width",
  "min-height",
  "max-width",
  "max-height",
  "display",
  "flex-direction",
  "justify-content",
  "align-items",
  "gap",
  "padding",
  "margin",
  "box-sizing",
  "overflow",
  "transform",
  "transform-origin",
  "opacity",
  "background",
  "border",
  "border-radius",
  "color",
  "font-family",
  "font-size",
  "font-style",
  "font-weight",
  "line-height",
  "letter-spacing",
  "text-align",
  "text-decoration",
  "vertical-align",
  "white-space",
  "object-fit",
  "fill",
  "stroke",
  "stroke-width",
  "stroke-dasharray",
];
function dataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}
