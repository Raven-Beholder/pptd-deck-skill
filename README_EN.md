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

<details>
<summary>Project management and project fonts</summary>

Click “Open Original Folder” to use the system folder picker. Save writes back to the selected original.
Click “Open as Copy” to select a source folder and destination. The copy gets its own subfolder, and Save writes there.
“Project Management” also offers Save a Copy, project download and temporary imports. A temporary copy asks for a destination on its first save.
Cancellation preserves the current project and drafts. Original saves check hashes and refuse to silently overwrite external edits.
macOS uses Finder; Windows uses its system folder dialog; Linux desktops need zenity or kdialog.
The picker appears on the computer running the local service. Without a desktop session, import a temporary copy and download the project.
Drag page thumbnails to reorder them. A placeholder marks the insertion point, and neighboring pages move smoothly.
Dragging near the top or bottom of the list scrolls it automatically; press Esc to cancel.
The editor supports theme colors in rich text and string table cells.
When table row or column proportions do not sum to 1, preview and export fit them proportionally to the bounds. Source values are retained, and preview notes explain the adjustment.

“Project Management → Project Fonts” offers 16 families: Source Han Sans and Serif in simplified and traditional Chinese, Inter, Source Sans 3, Source Serif 4, Lato, Carlito, Caladea, Montserrat, JetBrains Mono, IBM Plex Sans/Serif/Mono and STIX Two Math.
These recommended fonts use OFL-1.1. Adding them downloads pinned official versions, verifies hashes, and preserves full copyright and license notices.
Fonts live in the project's `fonts/` folder and use relative `customFonts` paths. Copies and project ZIPs include the fonts and notices.
The editor loads project fonts before drawing. Other computers need no system installation. Text without an explicit family uses the first regular project text font; math fonts have a separate role.
You may also add redistributable static TTF/OTF fonts that permit editable embedding. Each font is limited to 32 MiB, and the project to 100 MiB. TTC, WOFF and variable fonts are unsupported.
Enable “Embed Fonts” for PPT export, or use `--embed-fonts` in the CLI. Full fonts retain characters needed for future editing.
Missing families or styles, restricted embedding rights and corrupt fonts produce explicit errors. PPTX font loading still depends on the receiving application's support.
See the [project font guide](skills/pptd-deck-skill/reference/fonts.md).

Generation can use OFL fonts directly. For example, create a Chinese project with code and math fonts:

```sh
uv run --locked python skills/pptd-deck-skill/scripts/pipeline.py init --project /absolute/path/to/new-project --topic "Database introduction" --pages 12 --font-family source-han-sans --extra-font jetbrains-mono
```

This adds text and code fonts plus the default STIX Two Math, and writes relative `fonts.json` mappings.
Use `fonts list` to inspect the catalog and `fonts add` to add fonts to an existing project. The initial download needs a network; added fonts work offline.

</details>

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

PPTD authoring, editing and PPTX export are supported. Font embedding supports project-local static TTF/OTF resources. PPTX import and some complex effects are still unavailable. See the [native authoring guide](skills/pptd-deck-skill/reference/native-authoring.md) for details.

Layout previews use Pillow and approximate equation spacing. They do not replace rendering checks in PowerPoint, WPS or Keynote. Windows browser drag interactions and Chinese IME behavior still need manual checks.

## License

[MIT](LICENSE). See the [notices](THIRD_PARTY_NOTICES.md) for upstream copyright and external dependencies.

Maintainer: Raven-Beholder.
