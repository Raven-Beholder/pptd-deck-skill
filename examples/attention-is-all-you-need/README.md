# Attention Is All You Need · 论文导读

[English](README_EN.md)

给 agent 一篇论文和一句需求，让它自行完成组会汇报稿。
这个示例保留原始输入、最终 PPTX 和可编辑 PPTD 项目。

## 原始输入

附件：`1706.03762v7.pdf`，共 15 页。
来源：[Attention Is All You Need，arXiv v7](https://arxiv.org/abs/1706.03762v7)。

提示词原文也保存在 [prompt.txt](prompt.txt)：

> 请把这篇论文做成一份适合组会汇报的中文 PPT，讲清核心方法、关键实验和局限，图示尽量直观。

执行 subagent 从新上下文开始，使用本仓库的 [制作 skill](../../skills/pptd-deck-skill/SKILL.md)。
没有另行提供大纲、页数或设计方案。
项目目录和依赖环境由运行环境指定。
生成后按 skill 执行准备、逐页视觉检查和布局修复，再导出。

## 成品

agent 自行组织为 20 页，包含 19 页主讲和 1 页复现备查。

- [下载 PPTX](deck.pptx)
- [下载可编辑项目 ZIP](project.zip)
- [查看 PPTD 清单](deck.pptd)
- [查看逐页预览](previews/INDEX.md)

文字、公式、图示和图表保留可编辑结构。
本示例的对比图和表格由可编辑的形状、线条和文字组成。
逐页内容在 `pages/` 中，论文引用和实验口径在 [evidence.json](evidence.json) 中。
[brief.json](brief.json) 记录受众和制作目标。
论文 PDF 和字体文件没有随示例打包。

## 试用与修改

在仓库根目录完成依赖安装后，运行：

```sh
uv run --locked node bin/pptd-deck-skill.js serve examples/attention-is-all-you-need --open
```

网页编辑器会打开这份项目。选择页面和元素，修改文字、公式或图形，再保存并导出。
也可以解压项目 ZIP，将上述命令中的目录替换为解压目录。

若想从头生成，下载同一版本的论文 PDF，在已安装本 skill 的 agent 新对话中上传论文并粘贴原始提示词。
页数、内容组织和设计由 agent 自行选择。

示例引用系统字体，没有嵌入字体。
换一台机器时，可在编辑器中替换为已安装的中文字体。
需要重新执行严格布局检查时，配置本机字体映射，并按 [pipeline 指南](../../skills/pptd-deck-skill/reference/pipeline.md) 准备、检查和导出。

预览使用 Pillow 做布局检查，编辑器截图来自实际网页界面。
尚未在 PowerPoint、WPS 或 Keynote 中验收渲染。

## 来源

Vaswani et al. *Attention Is All You Need*. NeurIPS 2017，arXiv:1706.03762v7。
输入 PDF 的 SHA-256：

```text
bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697
```

公开示例不包含原论文 PDF。方法图示由 agent 用原生对象重绘，论文事实和数据保留来源标注。
本示例遵循仓库 [MIT 许可证](../../LICENSE)。原论文的权利归其作者及权利人所有。
