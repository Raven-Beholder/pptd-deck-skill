"""Explicit local-project selection and bounded portable project imports.

Folder uploads become a private temporary working copy. Nothing is installed,
and an upload never overwrites the original directory.
"""
import base64
import io
import json
from pathlib import Path, PurePosixPath
import tempfile
import shutil
import zipfile
import yaml
from native_project import Project, PROJECT_LIMIT, TEXT_LIMIT, asset_paths, page_value, parse
from native_project_fonts import FONT_LIMIT


def import_folder(files):
    if not isinstance(files, list) or not 1 <= len(files) <= 2000:
        raise ValueError('project import needs 1–2000 files')
    temporary = tempfile.TemporaryDirectory(prefix='pptd-local-project-')
    root = Path(temporary.name)
    try:
        seen, total = set(), 0
        for item in files:
            if not isinstance(item, dict):
                raise ValueError('invalid imported file')
            name = item.get('path')
            if (not isinstance(name, str) or not name or ':' in name or '\\' in name or
                    name != str(PurePosixPath(name)) or PurePosixPath(name).is_absolute() or
                    '..' in PurePosixPath(name).parts or name in seen):
                raise ValueError('invalid or duplicate project path')
            seen.add(name)
            encoded = item.get('data')
            limit = FONT_LIMIT if name.lower().endswith(('.ttf', '.otf')) else 20 * TEXT_LIMIT
            if not isinstance(encoded, str) or len(encoded) > (limit * 4 // 3 + 4):
                raise ValueError('imported file exceeds size limit')
            data = base64.b64decode(encoded, validate=True)
            if len(data) > limit:
                raise ValueError('imported file exceeds size limit')
            total += len(data)
            if total > PROJECT_LIMIT:
                raise ValueError('imported project exceeds 100 MiB')
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        project = Project(root)
        return temporary, project
    except Exception:
        temporary.cleanup()
        raise


def portable_font_config(project):
    """Carry self-contained QA mappings; never copy host font paths or files."""
    target = project.root / 'fonts.json'
    if not target.exists():
        return None, set()
    raw = project.read('fonts.json', TEXT_LIMIT)
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get('families', {}), dict):
        raise ValueError('invalid fonts.json mappings')
    assets = set()
    for mapping in [*value.get('families', {}).values(), value.get('math', {})]:
        if not isinstance(mapping, dict):
            raise ValueError('invalid fonts.json family mapping')
        for variant in ('regular', 'bold', 'italic', 'boldItalic'):
            if variant not in mapping:
                continue
            spec = mapping[variant]
            name = spec.get('path') if isinstance(spec, dict) else spec
            if not isinstance(name, str) or not name:
                raise ValueError('invalid fonts.json font path')
            if ':' in name or '\\' in name or PurePosixPath(name).is_absolute():
                return None, set()  # Installed-font configs are host-specific.
            if name != str(PurePosixPath(name)) or '..' in PurePosixPath(name).parts:
                raise ValueError('fonts.json portable path must stay inside the project')
            assets.add(name)
    return raw, assets


def project_archive(project, drafts, manifest_hash, hashes, theme=None):
    """Portable PPTD snapshot, including referenced local media and all drafts."""
    if not isinstance(drafts, dict) or not isinstance(hashes, dict):
        raise ValueError('expected project drafts and baseline hashes')
    with project.lock:
        current = project.current(manifest_hash)
        paths = {page['path'] for page in current['pages']}
        if set(drafts) - paths or any(hashes.get(p['path']) != p['hash'] for p in current['pages']):
            raise ValueError('project changed; preserve drafts before reopening')
        deck = current['deck']
        if theme is not None:
            if not isinstance(theme, dict):
                raise ValueError('theme must be a mapping')
            deck['theme'] = theme
        contents = {project.manifest: yaml.safe_dump(deck, allow_unicode=True, sort_keys=False).encode('utf-8')}
        assets = asset_paths(deck)
        config, font_assets = portable_font_config(project)
        if config is not None:
            contents['fonts.json'] = config
            assets.update(font_assets)
        for record in current['pages']:
            text = drafts.get(record['path'], record['text'])
            assets.update(asset_paths(page_value(parse(text))))
            contents[record['path']] = text.encode('utf-8')
        total = sum(map(len, contents.values()))
        for path in sorted(assets):
            if path in contents:
                raise ValueError('asset references a project source file')
            if total >= PROJECT_LIMIT:
                raise ValueError('project exceeds 100 MiB')
            data = project.read(path, min(FONT_LIMIT if path.lower().endswith(('.ttf', '.otf')) else 20 * TEXT_LIMIT, PROJECT_LIMIT - total))
            total += len(data)
            if total > PROJECT_LIMIT:
                raise ValueError('project exceeds 100 MiB')
            contents[path] = data
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path, data in sorted(contents.items()):
                archive.writestr(path, data)
        return result.getvalue()


def copy_project(project, destination, drafts=None, manifest_hash=None, hashes=None, theme=None):
    """Create a durable, unique project copy. Never overwrite a destination.

    Snapshot validation happens before any destination is created. The manifest
    is written last. A failed copy is removed without touching the source.
    """
    destination = Path(destination).resolve()
    if not destination.is_dir():
        raise ValueError('副本保存位置必须是已有文件夹。')
    loaded = project.load()
    data = project_archive(project, drafts or {}, manifest_hash or loaded['manifestHash'],
                           hashes if hashes is not None else {p['path']: p['hash'] for p in loaded['pages']}, theme)
    folder = Path(tempfile.mkdtemp(prefix=project.root.name[:80] + '-copy-', dir=destination))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = sorted(archive.namelist(), key=lambda name: name == project.manifest)
            for name in names:
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(archive.read(name))
        return Project(folder)
    except Exception:
        shutil.rmtree(folder)
        raise


def save_export(encoded, directory, filename):
    """Save an explicitly requested export without overwriting existing files."""
    import os
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError('请填写保存文件夹的绝对路径。')
    folder = Path(directory.strip()).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError('保存文件夹必须是已存在的绝对路径。')
    folder = folder.resolve()
    if (not isinstance(filename, str) or not filename.strip() or filename != filename.strip()
            or len(filename) > 160 or any(c in filename for c in '/\\:')
            or any(ord(c) < 32 for c in filename) or filename.startswith('.')):
        raise ValueError('文件名不能包含路径、控制字符或以点开头。')
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.pptx', '.png', '.svg'):
        raise ValueError('仅支持保存 PPTX、PNG 或 SVG。')
    if not isinstance(encoded, str) or len(encoded) > 140 * TEXT_LIMIT:
        raise ValueError('导出文件超过 100 MiB 保存限制。请使用浏览器下载。')
    data = base64.b64decode(encoded, validate=True)
    if not data or len(data) > PROJECT_LIMIT:
        raise ValueError('导出文件为空或超过 100 MiB 保存限制。')
    valid = (suffix == '.pptx' and data.startswith(b'PK\x03\x04')
             or suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n')
             or suffix == '.svg' and data.lstrip().startswith(b'<svg'))
    if not valid:
        raise ValueError('导出文件内容与扩展名不符。')
    # Link a complete temporary file into place exclusively. Collisions, including
    # symlinks, get a new name; no partially written output is ever published.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.pptd-export-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for index in range(1000):
            name = filename if index == 0 else f'{Path(filename).stem} ({index}){suffix}'
            target = folder / name
            try:
                os.link(temporary, target)
                return {'path': str(target), 'bytes': len(data)}
            except FileExistsError:
                continue
        raise ValueError('同名文件过多，请修改文件名。')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
