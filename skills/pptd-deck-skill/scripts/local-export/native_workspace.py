"""Explicit local-project selection and bounded portable project imports.

Folder uploads become a private temporary working copy. Nothing is installed,
and an upload never overwrites the original directory.
"""
import base64
import io
from pathlib import Path, PurePosixPath
import tempfile
import zipfile
import yaml
from native_project import Project, PROJECT_LIMIT, TEXT_LIMIT, asset_paths, page_value, parse


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
            if not isinstance(encoded, str) or len(encoded) > 28 * TEXT_LIMIT:
                raise ValueError('imported file exceeds 20 MiB')
            data = base64.b64decode(encoded, validate=True)
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
            data = project.read(path, min(20 * TEXT_LIMIT, PROJECT_LIMIT - total))
            total += len(data)
            if total > PROJECT_LIMIT:
                raise ValueError('project exceeds 100 MiB')
            contents[path] = data
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path, data in sorted(contents.items()):
                archive.writestr(path, data)
        return result.getvalue()


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
    if not isinstance(encoded, str) or len(encoded) > 28 * TEXT_LIMIT:
        raise ValueError('导出文件超过 20 MiB 保存限制。请使用浏览器下载。')
    data = base64.b64decode(encoded, validate=True)
    if not data or len(data) > 20 * TEXT_LIMIT:
        raise ValueError('导出文件为空或超过保存限制。')
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
