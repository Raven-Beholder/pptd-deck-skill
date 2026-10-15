#!/usr/bin/env python3
"""Build an auditable native-only review archive, never a licensing certificate.

An exact allowlist prevents the legacy editor, fonts, binaries, templates and
comparison oracles from entering this artifact. Source-only does not itself
establish rights or full feature parity. See THIRD_PARTY_NOTICES.md.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/pptd-deck-skill/scripts/local-export'
MODULES = (
    'native_cli', 'native_animation', 'native_common', 'native_effects', 'native_fill',
    'native_math', 'native_media', 'native_package', 'native_table', 'native_text', 'native_writer',
    'native_chart', 'native_chart_model', 'native_workbook', 'native_validation', 'native_project_fonts',
)
EDITOR_MODULES = ('native_editor', 'native_project', 'native_preview', 'native_fonts', 'native_workspace', 'native_picker', 'native_font_catalog')
EDITOR_ASSETS = ('index.html', 'app.mjs', 'model.mjs', 'styles.css', 'charts.mjs', 'text-format.mjs', 'shapes.mjs', 'math.mjs', 'playback.mjs', 'ui.mjs', 'images.mjs', 'icons.mjs', 'page-drag.mjs', 'project-fonts.mjs')
EDITOR_IMPORTS = set(EDITOR_MODULES) | {'http.server', 'socketserver', 'secrets', 'urllib.parse', 'urllib.request', 'threading', 'base64', 'uuid', 'subprocess', 'shutil'}
IMPORTS = set(MODULES) | {
    'argparse', 'json', 'os', 'pathlib', 'tempfile', 'zipfile', 'yaml', 'dataclasses',
    'math', 're', 'xml.etree.ElementTree', 'functools', 'hashlib', 'struct', 'posixpath',
    'html', 'html.parser', 'copy',
    'io', 'sys', 'urllib.parse',
}
README = '''# Native PPTD review build

This archive contains a standalone, readable Python exporter for a documented
subset of PPTD v2. It contains no legacy editor, WASM, vendor fonts, icons,
templates or third-party implementation. It never falls back to another exporter.
It is NOT a full replacement or a legal clearance; read NATIVE_NOTICE.md.

Python 3.12+ is required; prepare an isolated environment with the separately
licensed PyYAML dependency:

    python3 -m pip install -r requirements.txt
    python3 native_cli.py /path/to/deck.pptd --output /path/to/deck.pptx

Use --force to replace an existing output; --transition accepts fade or none.
Fonts are family references by default. Use --embed-fonts for declared local
static TTF/OTF customFonts resources. Include used families/styles and their
distribution notices. No font binaries are bundled with this archive.
Supported: rich-text subset, basic shapes/lines, local PNG/JPEG, shared fills,
outer shadows, tables, editable bar/line/pie/doughnut charts with embedded XLSX,
bounded editable formulas, basic entrance/exit animations.
Unsupported inputs fail explicitly. Full charts, SVG, variable/collection fonts and animation
coverage and cross-application acceptance are still pending.

MANIFEST.json records the exact source files, hashes and direct imports.
The import gate is a dependency regression check, not a malware or legal audit.
Development referenced open-pptd. See NATIVE_NOTICE.md for the MIT license
and external dependency notices.
'''


def source_payload(source=SOURCE, *, editor=False):
    payload, imports = {}, {}
    for module in MODULES + (EDITOR_MODULES if editor else ()):
        filename = module + '.py'
        path = source / filename
        if path.is_symlink():
            raise ValueError(f'allowlisted source must not be a symlink: {filename}')
        data = path.read_bytes()
        syntax = ast.parse(data, filename=filename)
        dependencies = set()
        for item in ast.walk(syntax):
            if isinstance(item, ast.Import):
                dependencies.update(alias.name for alias in item.names)
            elif isinstance(item, ast.ImportFrom):
                if item.level:
                    raise ValueError(f'unreviewed relative import: {filename}')
                dependencies.add(item.module)
            elif isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
                if item.func.id in ('__import__', 'eval', 'exec', 'compile'):
                    raise ValueError(f'unreviewed dynamic execution: {filename}: {item.func.id}')
        allowed = IMPORTS | (EDITOR_IMPORTS if editor else set())
        if dependencies - allowed:
            raise ValueError(f'unreviewed dependency in {filename}: {sorted(dependencies - allowed)}')
        payload[filename] = data
        imports[filename] = sorted(dependencies)
    notice = source / 'NATIVE_NOTICE.md'
    if notice.is_symlink():
        raise ValueError('source notice must not be a symlink')
    payload['NATIVE_NOTICE.md'] = notice.read_bytes()
    payload['README.md'] = README.encode()
    if editor:
        catalog = source / 'font-catalog.json'
        if catalog.is_symlink():
            raise ValueError('font catalog must not be a symlink')
        payload['font-catalog.json'] = catalog.read_bytes()
        payload['README.md'] = payload['README.md'].replace(
            b'It contains no legacy editor, WASM, vendor fonts, icons,\ntemplates or third-party implementation.',
            b'The exporter contains no legacy runtime, WASM, vendor fonts or templates.\nThe editor includes independently drawn toolbar SVGs; see ICONS_NOTICE.md.')
        icon_notice = source / 'ICONS_NOTICE.md'
        if icon_notice.is_symlink():
            raise ValueError('reference icon notice must not be a symlink')
        payload['ICONS_NOTICE.md'] = icon_notice.read_bytes()
        for name in EDITOR_ASSETS:
            path = source / 'native_editor' / name
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError(f'editor asset must not be a symlink: {name}')
            payload['native_editor/' + name] = path.read_bytes()
        payload['README.md'] += b'''\n## Native web editor with independently drawn toolbar SVGs (experimental)\n
    python3 native_editor.py /path/to/deck.pptd --port 55174

Open the full loopback URL printed by this command, including its fragment.
The browser supports blank projects and page creation/copy/removal/reordering.
Save affects the current page; Save All also saves the other drafts;
PPTX export includes all drafts without saving. Unsupported preview features
are labeled. The exporter rejects unsupported content without legacy fallback.
Structured editing preserves unknown fields but rewrites YAML formatting and
comments. Use source editing to preserve comments. Save checks hashes and
stages file replacement; it is not a cross-process filesystem CAS transaction.
Omit the project argument for a blank workspace with local-project opening.
Floating text/shape tools, themes, formulas, watermarks, tables/charts, deletion,
context menus, recoverable page structure edits, PNG/SVG export, portable
project download and bounded animation playback are implemented. Original
folder and durable-copy modes use system folder pickers. The recommended OFL
font catalog downloads pinned official files only when requested, and retains
license notices in the project. Static local fonts load before preview and can
be embedded as full EOT parts in PPTX. Page and manifest changes check hashes.
The toolbar uses independently drawn SVGs; read ICONS_NOTICE.md. No vendor runtime, remote fonts, CDN
or WASM is loaded. The native-only CLI profile excludes these icons. Selected GUI flows
were checked; large-deck performance and complete feature parity remain pending.
'''
    payload['requirements.txt'] = b'PyYAML==6.0.3\n'
    manifest = dict(schemaVersion=1, profile='native-editor-review' if editor else 'native-only-review',
                    entryPoint='native_editor.py' if editor else 'native_cli.py',
                    licensing='MIT; external dependencies retain their own licenses',
                    certifiedCleanRoom=False, fullReplacementAccepted=False,
                    thirdPartyAssets=[],
                    directImports=imports,
                    externalDependencies=[dict(name='PyYAML', version='6.0.3', license='MIT', bundled=False)],
                    files={name: dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                           for name, data in sorted(payload.items())})
    payload['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    return payload


def build(destination, source=SOURCE, *, editor=False):
    payload = source_payload(source, editor=editor)
    destination = Path(destination).absolute()
    if destination.suffix.lower() != '.zip':
        raise ValueError('native review archive must have a .zip extension')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-build-', dir=destination.parent) as staging:
        staged = Path(staging) / 'native.zip'
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(payload.items()):
                item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o100644 << 16
                archive.writestr(item, data)
        os.replace(staged, destination)
    return dict(output=str(destination), files=len(payload),
                sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                profile='native-editor-review' if editor else 'native-only-review')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--editor', action='store_true', help='include the web editor and independently drawn SVG icons')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output, editor=args.editor), indent=2))
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f'native-build: {exc}\n')
