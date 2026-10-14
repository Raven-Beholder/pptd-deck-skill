# PPTD Deck Skill

[中文](README.md)

Create presentations with an AI agent and revise them in a web editor.
The project includes a presentation skill, a PPTD editor and a local PPTX exporter.
Default outputs are an editable project folder and a PPTX with fade transitions.

Maintainer: Raven-Beholder.

## Features

- Edit text, equations, shapes, images, tables and basic charts.
- Update or delete theme text styles and colors.
- Check fonts, layout and sources before export.
- Preserve editable text, shapes, tables and Office Math in PPTX.

## Requirements

Install Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 18+.
uv manages Python 3.12 and installs dependencies in the project `.venv`.
Download caches and managed Python may live in your user directory.
This source installation needs no `npm install`.
The skill installer copies files; prepare the Python environment first.

## Installation

These commands install from source. Access permission is required while the repository is private.

### macOS and Linux

```sh
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
cd pptd-deck-skill
uv sync --locked --python 3.12
uv run --locked node bin/pptd-deck-skill.js install -y --target "$HOME/.codex/skills"
```

### Windows

Run in PowerShell:

```powershell
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
Set-Location pptd-deck-skill
uv sync --locked --python 3.12
uv run --locked node .\bin\pptd-deck-skill.js install -y --target "$env:USERPROFILE\.codex\skills"
```

The installed folder is `pptd-deck-skill` inside the target directory.
Reinstalling replaces that folder.
Shared agents can use `~/.agents/skills`; Claude Code uses `~/.claude/skills`.
Repeat `--target` to install into multiple directories.

`pyproject.toml` declares dependencies; `uv.lock` records versions and file hashes.
`uv sync --locked` checks that they agree.
Keep the environment available. Do not point `UV_PROJECT_ENVIRONMENT` at system Python.
Without uv, create a Python 3.12+ virtual environment and install `requirements.txt`.
Set `PYTHON` to its absolute interpreter path for the Node launcher.

## Usage

Ask your agent to read the installed `SKILL.md`, then provide a topic, audience and slide count.
Use `theme.md` to select an existing theme.
The agent should run scripts with the environment prepared at installation.
Local personal skills do not sync automatically to cloud tasks.

Start the editor from the repository:

```sh
uv run --locked node bin/pptd-deck-skill.js serve --open
```

This creates a blank project. To open an existing project:

```sh
uv run --locked node bin/pptd-deck-skill.js serve /absolute/path/to/project --open
```

The folder must contain a PPTD manifest and local resources.
Keep the complete service URL, including the session fragment.
Save or download your project before stopping the service.

The production workflow prepares, repairs, reviews and exports the project.
Source or font changes require fresh checks.
Before export, the agent provides an editor entry point for preview and revision.
See the [pipeline guide](skills/pptd-deck-skill/reference/pipeline.md).

## Development and testing

```sh
uv run --locked node tools/test_native.mjs
uv run --locked python tools/smoke_native_install.py
uv run --locked python tools/audit_native_tree.py
uv run --locked python tools/build_native_distribution.py --editor --output dist/editor.zip
npm run pack:check
```

CI runs on Linux, macOS and Windows.
Builds use a file allowlist and record hashes and module dependencies.
See the [icon preview](docs/native-icons-overview.svg).

## Scope

The release supports PPTD authoring, editing and PPTX export.
PPTX import, font embedding and some complex effects are unavailable.
Unsupported content produces an explicit error.

Pillow checks approximate layout and equation spacing.
Tests do not verify rendering in PowerPoint, WPS or Keynote.
Windows drag interactions and Chinese IME behavior still need manual checks.

Project license: [MIT](LICENSE). See the [notices](THIRD_PARTY_NOTICES.md) for the development reference and external dependencies.
