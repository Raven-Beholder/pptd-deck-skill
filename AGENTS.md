# Repository development

Use the repository's isolated environment: `uv sync --locked --python 3.12`.
Run commands with `uv run --locked`; no system-wide pip installation is needed.

For code changes, run `uv run --locked node tools/test_native.mjs`.
For installation or pipeline changes, also run `uv run --locked python tools/smoke_native_install.py`.
Before release, run the source audit and native build tools; preserve license/source notices.
Three-platform CI checks Windows, macOS and Linux. Linux checks do not certify GUI or Office rendering.

Read `skills/pptd-deck-skill/SKILL.md` for presentation authoring tasks.
Keep README.md and README_EN.md consistent.
Use short sentences, explicit instructions and consistent terminology.
Use Raven-Beholder as the maintainer display name. Retain upstream copyright notices.
Do not copy local absolute paths, personal email addresses, captured resources or private decks into release files.
