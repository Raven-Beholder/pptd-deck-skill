# PPTD Deck Skill

[English](README_EN.md)

用 AI agent 制作演示文稿，并在网页编辑器中修改内容。
项目提供制作 skill、PPTD 编辑器和本地 PPTX 导出器。
默认交付可编辑的项目目录和带淡入转场的 PPTX。

维护者：Raven-Beholder。

## 功能

- 编辑文字、公式、图形、图片、表格和基础图表。
- 修改或删除主题中的文字样式和颜色。
- 检查字体、布局和来源，修复后再导出。
- 保留 PPTX 中可编辑的文字、图形、表格和数学公式。

## 环境要求

安装 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Node.js 18+。
uv 管理 Python 3.12，将依赖安装到项目的 `.venv`。
下载缓存和 Python 运行时可能保存在用户目录。

当前使用源码安装，不需要运行 `npm install`。
安装 skill 只复制文件；请先准备 Python 环境。

## 安装

以下命令用于源码安装。仓库公开前，需要对应的访问权限。

### macOS 和 Linux

```sh
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
cd pptd-deck-skill
uv sync --locked --python 3.12
uv run --locked node bin/pptd-deck-skill.js install -y --target "$HOME/.codex/skills"
```

### Windows

在 PowerShell 中运行：

```powershell
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
Set-Location pptd-deck-skill
uv sync --locked --python 3.12
uv run --locked node .\bin\pptd-deck-skill.js install -y --target "$env:USERPROFILE\.codex\skills"
```

安装目录为目标目录下的 `pptd-deck-skill`。
重新安装会替换已有的同名 skill。
其他 agent 可以使用 `~/.agents/skills`；Claude Code 使用 `~/.claude/skills`。
通过 `--target` 指定目标目录，可以重复指定。

`pyproject.toml` 声明依赖，`uv.lock` 锁定版本和文件哈希。
`uv sync --locked` 会检查二者是否一致。
请保留项目环境，避免将 `UV_PROJECT_ENVIRONMENT` 指向系统 Python。

不用 uv 时，可用 Python 3.12+ 创建虚拟环境，再安装 `requirements.txt`。
将 `PYTHON` 设置为该环境解释器的绝对路径，供 Node 启动器使用。

## 使用

让 agent 读取安装目录中的 `SKILL.md`，再描述主题、受众和页数。
已有主题可通过 `theme.md` 指定。
运行脚本时，agent 应复用安装时的 Python 环境。
本机个人 skill 不会自动同步到云端。

在仓库目录中启动编辑器：

```sh
uv run --locked node bin/pptd-deck-skill.js serve --open
```

该命令创建空白项目。打开已有项目：

```sh
uv run --locked node bin/pptd-deck-skill.js serve /absolute/path/to/project --open
```

已有目录应包含 PPTD 清单和本地资源。
保留服务输出的完整地址，包括会话片段。
停止服务前，保存或下载项目。

制作流程依次执行准备、修复、检查和导出。
修改源文件或字体后，需要重新检查。
导出前，agent 会提供网页版编辑器的预览和返工入口。
详见 [pipeline 指南](skills/pptd-deck-skill/reference/pipeline.md)。

## 开发与测试

```sh
uv run --locked node tools/test_native.mjs
uv run --locked python tools/smoke_native_install.py
uv run --locked python tools/audit_native_tree.py
uv run --locked python tools/build_native_distribution.py --editor --output dist/editor.zip
npm run pack:check
```

CI 在 Linux、macOS 和 Windows 上运行测试。
构建使用文件白名单，并记录文件哈希和模块依赖。
图标示例见 [预览](docs/native-icons-overview.svg)。

## 使用范围

当前版本支持 PPTD 制作、编辑和 PPTX 导出。
尚不支持 PPTX 导入、字体嵌入和部分复杂特效。
不支持的内容会明确报错。

布局检查使用 Pillow，公式间距为近似值。
测试不代表 PowerPoint、WPS 或 Keynote 的实际渲染验收。
Windows 的浏览器拖拽和中文输入法仍需人工检查。

项目许可证：[MIT](LICENSE)。来源和第三方依赖见 [告知文件](THIRD_PARTY_NOTICES.md)。
