# Windows native setup and acceptance scope

Use Windows 10/11 or Windows Server with Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node 18+ installed.
Commands below are PowerShell. GitHub Actions validates Windows Server via
windows-latest; workstation browser/IME and Office GUI acceptance remain separate.

```powershell
git clone https://github.com/Raven-Beholder/pptd-deck-skill.git
Set-Location pptd-deck-skill
uv sync --locked --python 3.12
$env:PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
node .\bin\pptd-deck-skill.js install -y --target "$env:USERPROFILE\.codex\skills"
node .\bin\pptd-deck-skill.js serve --port 55174 --open
```

uv downloads Python 3.12 if needed and installs locked dependencies in .venv. From the repository, `uv run --locked python ...` also selects this environment. Alternatively, use an existing Python 3.12+ to create .venv and install requirements.txt with its interpreter. Do not use system-wide pip or point UV_PROJECT_ENVIRONMENT at system Python.

No WSL, Bash, Chromium automation, WASM, compiler or Node package installation
is needed for the native editor/exporter. Open the complete service URL printed
by the CLI. Keep the process running while editing; save writes UTF-8 YAML.
`PYTHON` chooses the same virtual-environment interpreter for Node launch/tests.
It only affects this PowerShell session and its child processes. Set it again in
a new session. An AI agent running elsewhere needs the explicit interpreter path
or the same dependencies in its own environment. The installer only copies skill
files; it does not install Python packages or configure other processes.

The default serve command opens a blank project. To open an existing project:
`node .\bin\pptd-deck-skill.js serve "C:\path with spaces\project" --open`.
The folder must already contain a PPTD manifest and referenced local resources.
Keep the virtual environment available, and save/download the project before
stopping a blank-project service. No npm registry release is required.

For layout QA, map an installed font in fonts.json, using forward slash resource
paths in PPTD pages. Chinese body text usually needs a CJK-capable family such as
Microsoft YaHei. Windows Server may not have optional CJK fonts: choose an
installed family covering the text, or install the Windows font/language package.
Missing glyphs fail QA and require repair; they are not silently accepted.

Typical font files are `C:/Windows/Fonts/msyh.ttc` and `cambria.ttc`. Collection
faces use an explicit index; choose it from the actual file. `pipeline init`
accepts --body-font-index and --math-font-index. Cambria Math is normally a
separate face in the Cambria collection. Do not assume a filename is a family
name. A fonts.json entry can use `{ "path":"C:/Windows/Fonts/cambria.ttc", "index":1 }`.

```powershell
& .\.venv\Scripts\python.exe .\skills\pptd-deck-skill\scripts\pipeline.py editor-info "C:\path with spaces\project\deck.pptd"
```

On Windows this prints a properly quoted PowerShell command with `&`, including
space/apostrophe-safe absolute arguments. Saved changes invalidate previous
prepare/review results. Review all pages and give the preview/rework notice before
export; scripts never operate a browser themselves.

Native export publishes on the destination's filesystem using staging and an
atomic no-clobber hard link. Use a local NTFS project/output location. Unsupported
network filesystems or hard-link restrictions return a repairable error and keep
previous output; they are not assumed compatible. Existing files require an
explicit authorized replacement with --force.

CI runs source tests, deterministic native/editor builds, package scan and a
post-install smoke in a path containing spaces and Chinese characters. That smoke
checks init, UTF-8 round trips, page save over loopback HTTP, native export,
prepare/review/export, source-change invalidation and XML/ZIP relationships.
Its receipt records whether a CJK-capable font was present. It does not test
PowerPoint/WPS rendering, browser drag/resize, Windows IME or every Windows edition.
