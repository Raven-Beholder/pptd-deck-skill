// Project fonts use authenticated local bytes. No CDN or system installation.
export class ProjectFonts {
  constructor() {
    this.faces = [];
    this.css = "";
  }
  clear() {
    for (const face of this.faces) document.fonts.delete(face);
    this.faces = [];
    this.css = "";
  }
  async load(resources, api) {
    this.clear();
    const entries = await Promise.all(resources.map(async (font) => {
      const blob = await api(`/api/font?path=${encodeURIComponent(font.src)}`, undefined, true);
      const face = new FontFace(font.family, await blob.arrayBuffer(), {
        weight: String(font.weight), style: font.style,
      });
      await face.load();
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("读取项目字体失败。"));
        reader.readAsDataURL(blob);
      });
      return { face, css: `@font-face{font-family:${JSON.stringify(font.family)};font-weight:${font.weight};font-style:${font.style};src:url(${JSON.stringify(data)})}` };
    }));
    for (const entry of entries) document.fonts.add(entry.face);
    this.faces = entries.map((entry) => entry.face);
    this.css = entries.map((entry) => entry.css).join("\n");
    await document.fonts.ready;
  }
}
