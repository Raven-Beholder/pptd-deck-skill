# PPTD Deck Skill

[中文](README.md) · [Quick start](#quick-start) · [Example project](examples/attention-is-all-you-need/README_EN.md) · [Documentation](#documentation)

PPTD Deck Skill gives AI agents the tools to create presentations. Provide a topic, document or paper to generate an editable PPTD project and a PPTX file. Use the companion web editor to refine the content and layout before presenting.

![Attention Is All You Need paper presentation: cover, architecture, equations and results](docs/showcase/attention-is-all-you-need/slides.webp)

Four layout previews from a Chinese presentation on *Attention Is All You Need*. [Download PPTX](examples/attention-is-all-you-need/deck.pptx) · [Download editable project](examples/attention-is-all-you-need/project.zip) · [View full example](examples/attention-is-all-you-need/README_EN.md)

## Quick start

### 1. Install the skill

Requires Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 18+. uv prepares Python 3.12 and the project dependencies. No `npm install` is needed.

macOS / Linux:

```sh
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
cd pptd-deck-skill
uv sync --locked --python 3.12
uv run --locked node bin/pptd-deck-skill.js install -y --target "$HOME/.codex/skills"
```

<details>
<summary>Windows (PowerShell)</summary>

```powershell
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
Set-Location pptd-deck-skill
uv sync --locked --python 3.12
uv run --locked node .\bin\pptd-deck-skill.js install -y --target "$env:USERPROFILE\.codex\skills"
```

</details>

<details>
<summary>Other agents and the Python environment</summary>

Use `--target` to select your agent's skill directory. Repeat it to install into multiple directories. A shared location is `~/.agents/skills`; Claude Code uses `~/.claude/skills`. The installed folder is named `pptd-deck-skill`. Reinstalling replaces that folder.

The installer copies skill files. Scripts still use the Python environment prepared in this repository. Keep the checkout and `.venv` available, and ask your agent to follow the environment instructions in `SKILL.md`. Locally installed skills do not sync automatically to cloud tasks.

`pyproject.toml` declares dependencies; `uv.lock` pins versions. Download caches and managed Python may live in your user directory.

</details>

### 2. Create a presentation

Ask your agent to use `pptd-deck-skill`, then describe what you need. For example, attach the PDF of [Attention Is All You Need](https://arxiv.org/abs/1706.03762v7) and enter:

> 请把这篇论文做成一份适合组会汇报的中文 PPT，讲清核心方法、关键实验和局限，图示尽量直观。

Translation: Turn this paper into a Chinese presentation for a lab meeting. Explain the core method, key experiments and limitations, with clear diagrams.

The example above was generated from this prompt. Its 20 slides cover the method, experimental comparisons and discussion. You can also specify an audience, slide count or visual style, or provide an existing theme through `theme.md`.

The outputs are a PPTX and an editable project folder. The [full example](examples/attention-is-all-you-need/README_EN.md) includes the original prompt, paper source and every slide.

## Web editor

The web editor runs locally and can open PPTD projects on its own. Select a slide or element to edit text, equations, shapes and layout, then save and export a PPTX.

![PPTD web editor: slide navigation, canvas, text tools and properties](docs/showcase/attention-is-all-you-need/editor.webp)

Open the example from the repository:

```sh
uv run --locked node bin/pptd-deck-skill.js serve examples/attention-is-all-you-need --open
```

Create a blank project:

```sh
uv run --locked node bin/pptd-deck-skill.js serve --open
```

To open another project, pass its folder after `serve`. Keep the complete service URL and save or download your project before stopping the service.

## Features

- **Editable output**: keep text, shapes, tables and equations available for further changes.
- **Equation typesetting**: use common LaTeX syntax and export editable Office Math objects.
- **Theme styles**: set fonts, colors and text styles across the deck, or adjust individual elements.
- **Checks and export**: check fonts, layout and source records, then generate a PPTX with fade transitions by default.

## Documentation

- [Authoring, review and export workflow](skills/pptd-deck-skill/reference/pipeline.md)
- [PPTD file format](skills/pptd-deck-skill/reference/pptd.md)
- [Native authoring support](skills/pptd-deck-skill/reference/native-authoring.md)
- [Themes and design presets](theme_EN.md)
- [Windows guide](skills/pptd-deck-skill/reference/windows.md)

## Development

Run in the repository's isolated environment:

```sh
uv run --locked node tools/test_native.mjs
uv run --locked python tools/smoke_native_install.py
uv run --locked python tools/audit_native_tree.py
uv run --locked python tools/build_native_distribution.py --editor --output dist/editor.zip
npm run pack:check
```

CI covers macOS, Windows and Linux. Builds use a file allowlist and record hashes and module dependencies. See the [icon preview](docs/native-icons-overview.svg).

## Current support

PPTD authoring, editing and PPTX export are supported. PPTX import, font embedding and some complex effects are still unavailable. See the [native authoring guide](skills/pptd-deck-skill/reference/native-authoring.md) for details.

Layout previews use Pillow and approximate equation spacing. They do not replace rendering checks in PowerPoint, WPS or Keynote. Windows browser drag interactions and Chinese IME behavior still need manual checks.

## License

[MIT](LICENSE). See the [notices](THIRD_PARTY_NOTICES.md) for upstream copyright and external dependencies.

Maintainer: Raven-Beholder.
