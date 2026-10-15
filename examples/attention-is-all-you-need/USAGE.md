# 示例项目使用说明

维护者：Raven-Beholder。

这是中文学术组会汇报示例，共20页。前19页适合主讲，第20页用于复现讨论。所有正文、公式、流程图、表格与对比图由可编辑对象组成。

- `deck.pptd` 是项目入口。`pages/` 保存逐页源文件。
- `deck.pptx` 是对应的 PowerPoint 文件。
- `brief.json` 记录任务、受众与设计选择。
- `evidence.json` 和 `SOURCES.md` 记录数据口径、计算与逐页论文位置。
- `previews/` 保存逐页 PNG 与总览。PNG 是 Pillow 布局预览，不代表 Office、WPS 或 Keynote 实测效果。

使用仓库的隔离环境。先在仓库根目录运行 `uv sync --locked --python 3.12`。

在仓库根目录获取网页版编辑器启动命令：

```sh
uv run --locked python skills/pptd-deck-skill/scripts/pipeline.py editor-info examples/attention-is-all-you-need/deck.pptd
```

修改保存后，重新执行 `prepare`、逐页查看、`review` 和 `export`。用 `--fonts` 指向项目之外的本地字体映射文件。流水线会在项目旁生成 `.pipeline/` 检查报告。对外分享项目时，排除此目录与本地字体映射。

正文声明字体为 Arial Unicode MS，公式以 Office Math 保存。字体不嵌入。请将正文替换为本机已安装、覆盖中英文的字体，并配置对应真实字体文件后重新检查。不要分发系统字体文件。

预览中的粗体与数学斜体使用合成样式。公式间距是近似预览。没有进行 Office、WPS 或 Keynote 应用内渲染验证。

论文来源、版本、图表权利说明及数值冲突见 `SOURCES.md`。项目不包含论文 PDF。
