"""Local editor project I/O. No legacy runtime or third-party frontend code.

Existing pages use conflict-aware atomic saves. Page structure is published
last, with server-generated new paths and recoverable removal. Drafts retain
unrecognized fields; export uses the strict native writer and never falls back.
"""
import hashlib
import base64
import math
import os
from pathlib import Path, PurePosixPath
import tempfile
import threading
import uuid

import yaml

from native_writer import export_native
from native_media import image_size
from native_project_fonts import FONT_LIMIT, font_info, require_editable, project_fonts
from native_validation import verify_output
from native_export_audit import verify_content

TEXT_LIMIT = 1024 * 1024
PROJECT_LIMIT = 100 * 1024 * 1024


class ConflictError(ValueError):
    """A file changed since the editor loaded it; preserve the external edit."""


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError('YAML keys must be unique strings')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def json_value(value, depth=0, budget=None):
    """Bound recursive input and reject YAML-only types before browser transport."""
    budget = budget if budget is not None else [100000]
    budget[0] -= 1
    if depth > 48 or budget[0] < 0:
        raise ValueError('document exceeds editor complexity limit')
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError('mapping keys must be strings')
            json_value(child, depth + 1, budget)
    elif isinstance(value, list):
        for child in value:
            json_value(child, depth + 1, budget)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ValueError('only JSON-compatible YAML values are supported')
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            valid = math.isfinite(value) and abs(value) <= 2 ** 53 - 1
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError('number exceeds browser-safe range')
    elif isinstance(value, str):
        value.encode('utf-8')  # Reject lone surrogates before writing a file.
    return value


def parse(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > TEXT_LIMIT:
        raise ValueError('YAML exceeds 1 MiB editor limit')
    depth = 0
    for event in yaml.parse(text, Loader=UniqueLoader):
        if isinstance(event, yaml.AliasEvent):
            raise ValueError('YAML aliases are not supported by the editor')
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > 48:
                raise ValueError('YAML nesting exceeds editor limit')
        if isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    value = json_value(yaml.load(text, Loader=UniqueLoader))
    if not isinstance(value, dict):
        raise ValueError('expected a YAML mapping')
    return value


def page_value(value):
    json_value(value)
    if not isinstance(value, dict) or not isinstance(value.get('elements'), list):
        raise ValueError('page.elements must be an array')
    if len(value['elements']) > 2000:
        raise ValueError('page exceeds 2000 element editor limit')
    ids = set()
    for element in value['elements']:
        if not isinstance(element, dict):
            raise ValueError('elements must be mappings')
        identifier = element.get('elementId')
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError('elementId must be a unique nonempty string')
        ids.add(identifier)
        bounds = element.get('bounds')
        if (not isinstance(bounds, list) or len(bounds) != 4 or
                any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in bounds) or
                min(bounds[2:]) <= 0):
            raise ValueError('element bounds must be [x, y, positive width, positive height]')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def asset_paths(value):
    paths = set()
    if isinstance(value, dict):
        if isinstance(value.get('src'), str):
            paths.add(value['src'])
        if isinstance(value.get('family'), str) and isinstance(value.get('src'), str) and isinstance(value.get('license'), str):
            paths.add(value['license'])
        for child in value.values():
            paths.update(asset_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.update(asset_paths(child))
    return paths


class Project:
    def __init__(self, manifest):
        manifest = Path(manifest).resolve()
        if manifest.is_dir():
            candidates = sorted(manifest.glob('*.pptd'))
            if len(candidates) != 1:
                raise ValueError('directory must contain exactly one .pptd manifest')
            manifest = candidates[0]
        if manifest.suffix != '.pptd' or not manifest.is_file():
            raise ValueError('expected an existing .pptd manifest')
        self.root, self.manifest = manifest.parent, manifest.name
        self.lock = threading.RLock()
        self.load()

    def path(self, name):
        if (not isinstance(name, str) or not name or ':' in name or '\\' in name or
                name != str(PurePosixPath(name)) or
                PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts):
            raise ValueError('expected a canonical relative project path')
        target = self.root
        for part in PurePosixPath(name).parts:
            target = target / part
            if target.is_symlink():
                raise ValueError('project symlinks are not supported')
        if not target.is_file() or not target.resolve().is_relative_to(self.root):
            raise ValueError('project file is missing or outside project')
        return target

    def read(self, name, limit=TEXT_LIMIT):
        with self.path(name).open('rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('project file exceeds editor size limit')
        return data

    def load(self):
        with self.lock:
            raw = self.read(self.manifest)
            deck = parse(raw.decode('utf-8'))
            paths = deck.get('pages')
            size = deck.get('size')
            if (deck.get('version') != 'v2' or not isinstance(paths, list) or not paths or
                    len(paths) > 500 or any(not isinstance(p, str) for p in paths) or
                    len(set(paths)) != len(paths) or self.manifest in paths):
                raise ValueError('expected PPTD v2 with 1–500 unique page paths')
            if (not isinstance(size, list) or len(size) != 2 or
                    any(isinstance(n, bool) or not isinstance(n, (int, float)) or not 1 <= n <= 10000 for n in size)):
                raise ValueError('slide size must be within 1–10000 points')
            pages, total = [], len(raw)
            for path in paths:
                data = self.read(path)
                total += len(data)
                if total > 16 * TEXT_LIMIT:
                    raise ValueError('project YAML exceeds 16 MiB editor limit')
                text = data.decode('utf-8')
                pages.append(dict(path=path, text=text, hash=digest(data), page=page_value(parse(text))))
            fonts = project_fonts(self.root, deck.get('customFonts'), allow_missing=True)
            return dict(manifest=self.manifest, manifestHash=digest(raw), deck=deck, pages=pages,
                        fonts=[font.public() for font in fonts])

    def current(self, manifest_hash):
        current = self.load()
        if manifest_hash != current['manifestHash']:
            raise ConflictError('项目清单已被外部修改，请保留草稿并重新载入。')
        return current

    def save(self, name, text, expected_hash, manifest_hash):
        page_value(parse(text))
        with self.lock:
            current = self.current(manifest_hash)
            pages = {p['path']: p for p in current['pages']}
            if name not in pages:
                raise ValueError('only existing manifest pages can be saved')
            if pages[name]['hash'] != expected_hash:
                raise ConflictError('此页已被外部修改，未覆盖磁盘文件。请下载草稿后重新载入。')
            target = self.path(name)
            data = text.encode('utf-8')
            # Same-directory staging avoids exposing a partially written page.
            # Hash checks detect prior edits; this is not an OS-wide CAS lock.
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.pptd-edit-', delete=False) as stream:
                staged = Path(stream.name)
                try:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.close()  # Windows cannot publish or unlink an open staging file.
                    os.chmod(staged, target.stat().st_mode & 0o777)
                    if digest(self.read(name)) != expected_hash:
                        raise ConflictError('保存期间此页被修改，未覆盖磁盘文件。')
                    os.replace(staged, target)
                finally:
                    stream.close()
                    staged.unlink(missing_ok=True)
            return dict(hash=digest(data))

    def arrange_pages(self, entries, manifest_hash, hashes=None):
        """Publish page order last; deleted pages remain recoverable on disk.

        New names are generated here, never supplied by the browser. All pages
        are validated before any write. A failed publish leaves only unreferenced
        new files, never a manifest that points at incomplete content.
        """
        if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
            raise ValueError('项目必须包含 1–500 页。')
        with self.lock:
            current = self.current(manifest_hash)
            if hashes is not None and (not isinstance(hashes, dict) or
                    any(hashes.get(page['path']) != page['hash'] for page in current['pages'])):
                raise ConflictError('页面被外部修改，未更改清单；请保留草稿后重新载入。')
            names, created = [], []
            for entry in entries:
                if isinstance(entry, str):
                    if entry == self.manifest:
                        raise ValueError('manifest cannot be a page')
                    raw = self.read(entry)
                    page_value(parse(raw.decode('utf-8')))
                    if hashes is not None and hashes.get(entry) != digest(raw):
                        raise ConflictError('待恢复页面被外部修改，未更改清单。')
                    name = entry
                elif isinstance(entry, dict):
                    value = page_value(entry)
                    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
                    page_value(parse(text))
                    name = 'native-page-' + uuid.uuid4().hex + '.yaml'
                    created.append((name, text.encode('utf-8')))
                else:
                    raise ValueError('page entry must be a path or page mapping')
                if name in names:
                    raise ValueError('duplicate page path')
                names.append(name)
            deck = current['deck']
            deck['pages'] = names
            data = yaml.safe_dump(deck, allow_unicode=True, sort_keys=False).encode('utf-8')
            parse(data.decode('utf-8'))
            if len(data) + sum(len(self.read(name)) for name in names if name not in dict(created)) + sum(len(raw) for _, raw in created) > 16 * TEXT_LIMIT:
                raise ValueError('project YAML exceeds 16 MiB editor limit')
            for name, raw in created:
                with (self.root / name).open('xb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.close()  # Windows cannot publish or unlink an open staging file.
            self._publish_manifest(data, manifest_hash)
            return self.load()

    def _publish_manifest(self, data, expected_hash):
        target = self.path(self.manifest)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.pptd-manifest-', delete=False) as stream:
            staged = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()  # Windows cannot publish or unlink an open staging file.
                os.chmod(staged, target.stat().st_mode & 0o777)
                if digest(self.read(self.manifest)) != expected_hash:
                    raise ConflictError('保存期间清单被修改，未覆盖磁盘文件。')
                os.replace(staged, target)
            finally:
                stream.close()
                staged.unlink(missing_ok=True)

    def save_theme(self, theme, manifest_hash):
        json_value(theme)
        if not isinstance(theme, dict):
            raise ValueError('theme must be a mapping')
        with self.lock:
            current = self.current(manifest_hash)
            deck = current['deck']
            deck['theme'] = theme
            data = yaml.safe_dump(deck, allow_unicode=True, sort_keys=False).encode('utf-8')
            parse(data.decode('utf-8'))  # Never publish a manifest the editor cannot reopen.
            target = self.path(self.manifest)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.pptd-theme-', delete=False) as stream:
                staged = Path(stream.name)
                try:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.close()  # Windows cannot publish or unlink an open staging file.
                    os.chmod(staged, target.stat().st_mode & 0o777)
                    if digest(self.read(self.manifest)) != manifest_hash:
                        raise ConflictError('保存主题期间清单被修改，未覆盖磁盘文件。')
                    os.replace(staged, target)
                finally:
                    stream.close()
                    staged.unlink(missing_ok=True)
            return dict(manifestHash=digest(data))

    def export(self, drafts, manifest_hash, hashes=None, theme=None, transition="fade", embed_fonts=False, *, with_report=False):
        if transition not in ("none", "fade"):
            raise ValueError("unsupported slide transition")
        if not isinstance(embed_fonts, bool):
            raise ValueError('embedFonts must be a boolean')
        if not isinstance(drafts, dict):
            raise ValueError('drafts must be a mapping of page paths to YAML strings')
        with self.lock:
            current = self.current(manifest_hash)
            paths = {page['path'] for page in current['pages']}
            if set(drafts) - paths:
                raise ValueError('draft page is not in manifest')
            if hashes is not None and (not isinstance(hashes, dict) or
                    any(hashes.get(page['path']) != page['hash'] for page in current['pages'])):
                raise ConflictError('项目页面已被外部修改，导出已停止；请保留草稿后重新载入。')
            contents = {self.manifest: self.read(self.manifest)}
            deck = current['deck']
            if theme is not None:
                json_value(theme)
                if not isinstance(theme, dict):
                    raise ValueError('theme must be a mapping')
                deck['theme'] = theme
                contents[self.manifest] = yaml.safe_dump(deck, allow_unicode=True, sort_keys=False).encode('utf-8')
            # Missing font files are optional export resources. Keep their
            # declarations and family names, but do not treat them as images.
            assets = asset_paths({key: value for key, value in deck.items() if key != 'customFonts'})
            available = {font['src'] for font in current['fonts']}
            for entry in deck.get('customFonts', []):
                if entry['src'] in available:
                    assets.update(asset_paths(entry))
            for page in current['pages']:
                text = drafts.get(page['path'], page['text'])
                value = page_value(parse(text))
                assets.update(asset_paths(value))
                contents[page['path']] = text.encode('utf-8')
            total = sum(map(len, contents.values()))
            for path in sorted(assets):
                if path in contents:
                    raise ValueError('image source cannot reference a project text file')
                if total >= PROJECT_LIMIT:
                    raise ValueError('project assets exceed 100 MiB editor limit')
                data = self.read(path, min(FONT_LIMIT if path.lower().endswith(('.ttf', '.otf')) else 20 * TEXT_LIMIT, PROJECT_LIMIT - total))
                total += len(data)
                contents[path] = data
            with tempfile.TemporaryDirectory(prefix='native-editor-export-') as directory:
                root = Path(directory)
                for path, data in contents.items():
                    # Every name was checked against the original project root.
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                output = root / 'output.pptx'
                export_native(root / self.manifest, output, transition, parse, embed_fonts=embed_fonts)
                report = verify_output(output, transition, embed_fonts)
                verify_content(root / self.manifest, output)
                data = output.read_bytes()
                return (data, report) if with_report else data

    def font(self, name):
        if name not in {entry.src for entry in project_fonts(self.root, self.load()['deck'].get('customFonts'), allow_missing=True)}:
            raise ValueError('font is not declared in project')
        data = self.read(name, FONT_LIMIT)
        require_editable(font_info(data))
        return data, 'font/otf' if data[:4] == b'OTTO' else 'font/ttf'

    def import_font(self, encoded, manifest_hash, *, license_path=None):
        if not isinstance(encoded, str) or len(encoded) > 44 * TEXT_LIMIT:
            raise ValueError('font import exceeds 32 MiB limit')
        data = base64.b64decode(encoded, validate=True)
        return self.import_font_bundle([data], manifest_hash, license_path=license_path)

    def import_font_bundle(self, resources, manifest_hash, *, notice=None, notice_name=None, license_path=None, role='text'):
        if not isinstance(resources, list) or not 1 <= len(resources) <= 64:
            raise ValueError('font bundle needs 1–64 faces')
        descriptions = [(data, font_info(data)) for data in resources]
        for _, info in descriptions:
            require_editable(info)
            if role not in ('text', 'math') or role == 'math' and not info['math']:
                raise ValueError('math font requires an OpenType MATH table')
        with self.lock:
            current = self.current(manifest_hash)
            folder = self.root / 'fonts'
            if folder.is_symlink():
                raise ValueError('project font folder cannot be a symlink')
            folder.mkdir(exist_ok=True)
            def store(name, data):
                target = self.root / name
                if target.is_symlink():
                    raise ValueError('font target cannot be a symlink')
                if target.exists():
                    if self.read(name, FONT_LIMIT) != data:
                        raise ConflictError('existing font resource was modified')
                    return
                with tempfile.NamedTemporaryFile(dir=folder, prefix='.pptd-font-', delete=False) as stream:
                    staged = Path(stream.name)
                    try:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                        stream.close()
                        os.link(staged, target)
                    finally:
                        staged.unlink(missing_ok=True)
            if notice is not None:
                if not isinstance(notice, str) or not 0 < len(notice.encode('utf-8')) <= TEXT_LIMIT or not isinstance(notice_name, str) or not all(c.isascii() and (c.isalnum() or c == '-') for c in notice_name):
                    raise ValueError('invalid font license notice')
                raw_notice = notice.encode('utf-8')
                license_path = 'fonts/' + notice_name + '-OFL-' + digest(raw_notice)[:16] + '.txt'
                store(license_path, raw_notice)
            if license_path:
                self.path(license_path)
            deck = current['deck']
            entries = deck.get('customFonts', [])
            for data, info in descriptions:
                name = 'fonts/' + digest(data) + '.' + info['format']
                store(name, data)
                entry = dict(family=info['family'], src=name, weight=700 if info['bold'] else 400,
                             style='italic' if info['italic'] else 'normal')
                if role == 'math':entry['role'] = role
                if license_path:
                    entry['license'] = license_path
                entries = [item for item in entries
                           if (item['family'], item.get('weight', 400), item.get('style', 'normal')) !=
                              (entry['family'], entry['weight'], entry['style'])]
                entries.append(entry)
            project_fonts(self.root, entries)
            deck['customFonts'] = entries
            raw = yaml.safe_dump(deck, allow_unicode=True, sort_keys=False).encode('utf-8')
            parse(raw.decode('utf-8'))
            self._publish_manifest(raw, manifest_hash)
            return dict(manifestHash=digest(raw), customFonts=entries,
                        fonts=[font.public() for font in project_fonts(self.root, entries)])

    def image(self, name):
        data = self.read(name, 20 * TEXT_LIMIT)
        _, _, kind = image_size(data)
        return data, 'image/' + kind

    def import_image(self, encoded):
        """Store an explicitly imported local image by content hash.

        Page references are drafts until Save. An unused imported resource is
        retained if the user undoes insertion; no existing resource is deleted.
        """
        if not isinstance(encoded, str) or len(encoded) > 14 * TEXT_LIMIT:
            raise ValueError('image import exceeds 10 MiB limit')
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError('invalid image encoding') from exc
        if not data or len(data) > 10 * TEXT_LIMIT:
            raise ValueError('image import exceeds 10 MiB limit')
        width, height, kind = image_size(data)
        with self.lock:
            folder = self.root / 'native-media'
            if folder.is_symlink():
                raise ValueError('image import directory must not be a symlink')
            folder.mkdir(exist_ok=True)
            name = 'native-media/' + digest(data) + ('.png' if kind == 'png' else '.jpg')
            target = folder / Path(name).name
            if target.is_symlink():
                raise ValueError('imported image target must not be a symlink')
            if target.exists():
                if self.read(name, 10 * TEXT_LIMIT) != data:
                    raise ConflictError('已有同名资源的内容不同，未覆盖文件。')
            else:
                with tempfile.NamedTemporaryFile(dir=folder, prefix='.image-import-', delete=False) as stream:
                    staged = Path(stream.name)
                    try:
                        stream.write(data); stream.flush(); os.fsync(stream.fileno())
                        stream.close()  # Windows cannot publish or unlink an open staging file.
                        try:
                            os.link(staged, target)
                        except FileExistsError:
                            if self.read(name, 10 * TEXT_LIMIT) != data:
                                raise ConflictError('导入期间资源被修改，未覆盖文件。')
                    finally:
                        stream.close()
                        staged.unlink(missing_ok=True)
            return dict(path=name, width=width, height=height)
