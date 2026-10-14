#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
command -v uv >/dev/null || { echo 'Install uv in the cloud environment, then retry.' >&2; exit 1; }
command -v node >/dev/null || { echo 'Install Node.js 22 in the cloud environment, then retry.' >&2; exit 1; }
uv sync --locked --python 3.12
uv run --locked node tools/test_native.mjs
uv run --locked python tools/smoke_native_install.py
