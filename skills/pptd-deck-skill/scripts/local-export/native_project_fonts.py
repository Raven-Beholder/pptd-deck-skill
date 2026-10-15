"""Portable local SFNT resources and full-font EOT packaging.

Original implementation from the OpenType OS/2/name specifications and the
Microsoft EOT submission: https://www.w3.org/submissions/EOT/
No font binaries, compression runtime, font downloads or installed-font copying.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import struct
import xml.etree.ElementTree as ET

from native_common import NS, NativeExportError, fields, node, string

FONT_LIMIT = 32 * 1024 * 1024
FONT_TOTAL_LIMIT = 100 * 1024 * 1024


def font_info(data):
    """Validate bounded static TTF/OTF tables and read names/embedding rights."""
    if not isinstance(data, bytes) or not 12 <= len(data) <= FONT_LIMIT:
        raise NativeExportError('字体文件为空或超过 32 MiB。')
    if data[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'true'):
        raise NativeExportError('项目字体目前支持独立 TTF/OTF 文件；不支持 TTC、WOFF 或 EOT。')
    count = struct.unpack_from('>H', data, 4)[0]
    end = 12 + count * 16
    if not 1 <= count <= 128 or end > len(data):
        raise NativeExportError('invalid SFNT table directory')
    tables, spans = {}, []
    for tag, _, offset, length in struct.iter_unpack('>4sIII', data[12:end]):
        if tag in tables or offset < end or offset + length > len(data):
            raise NativeExportError('duplicate or out-of-bounds SFNT table')
        tables[tag] = data[offset:offset + length]
        if length:
            spans.append((offset, offset + length))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise NativeExportError('overlapping SFNT tables')
    required = {b'head': 54, b'maxp': 6, b'OS/2': 68, b'name': 6, b'cmap': 4}
    if any(len(tables.get(tag, b'')) < length for tag, length in required.items()):
        raise NativeExportError('font lacks required head/maxp/OS2/name/cmap tables')
    if not ({b'glyf', b'loca'} <= set(tables) or b'CFF ' in tables):
        raise NativeExportError('font lacks TrueType or CFF outlines')
    if b'fvar' in tables:
        raise NativeExportError('请使用静态 TTF/OTF 字体，暂不支持可变字体。')
    names = tables[b'name']
    _, n, storage = struct.unpack_from('>HHH', names)
    if n > 4096 or storage < 6 + n * 12 or storage > len(names):
        raise NativeExportError('invalid font name table')
    values, aliases = {}, set()
    for platform, encoding, language, identifier, length, offset in struct.iter_unpack('>HHHHHH', names[6:6 + n * 12]):
        if identifier not in (1, 2, 4, 5, 13, 14, 16, 17):
            continue
        if storage + offset + length > len(names) or length > 8192:
            raise NativeExportError('font name outside table')
        codec = 'utf-16-be' if platform in (0, 3) else 'mac_roman' if platform == 1 and encoding == 0 else None
        if codec is None:
            continue
        try:
            value = names[storage + offset:storage + offset + length].decode(codec).strip()
        except UnicodeError as exc:
            raise NativeExportError('invalid font name encoding') from exc
        if not value or any(ord(char) < 32 for char in value):
            continue
        if identifier in (1, 16):
            aliases.add(value)
        priority = 0 if platform == 3 and language == 1033 else 1 if platform == 0 else 2
        if identifier not in values or priority < values[identifier][0]:
            values[identifier] = (priority, value)
    get = lambda identifier, default='': values.get(identifier, (0, default))[1]
    family = get(16, get(1))
    if not family or len(family) > 200:
        raise NativeExportError('font lacks a usable family name')
    os2 = tables[b'OS/2']
    version, _, weight, _, rights = struct.unpack_from('>HhHHH', os2)
    selection = struct.unpack_from('>H', os2, 62)[0]
    permissions = rights & 15
    # Older OS/2 versions allow multiple permission bits; use the least
    # restrictive defined value, while retaining the original bits in EOT.
    editable = permissions == 0 or bool(permissions & 8)
    bitmap_only = version >= 2 and bool(rights & 0x200)
    if permissions & 1 or version >= 3 and permissions not in (0, 2, 4, 8):
        raise NativeExportError('invalid font embedding permission bits')
    return dict(family=family, aliases=sorted(aliases), subfamily=get(17, get(2, 'Regular')),
                fullName=get(4, family), versionName=get(5, 'Version 1.0'),
                eotFamily=get(1, family), eotStyle=get(2, 'Regular'),
                weight=weight, bold=bool(selection & 0x20) or weight >= 600,
                italic=bool(selection & 1), rights=rights, editable=editable and not bitmap_only,
                license=get(13), licenseUrl=get(14), format='otf' if data[:4] == b'OTTO' else 'ttf',
                math=b'MATH' in tables,
                panose=os2[32:42], unicodeRanges=struct.unpack_from('>4I', os2, 42),
                codePageRanges=struct.unpack_from('>2I', os2, 78) if len(os2) >= 86 else (0, 0),
                checksum=struct.unpack_from('>I', tables[b'head'], 8)[0])


def require_editable(info):
    if not info['editable']:
        raise NativeExportError(f"字体 {info['family']} 不允许可编辑嵌入，不能加入可编辑项目。请使用允许分发和编辑嵌入的字体。")


def local_font_path(root, relative):
    if (not isinstance(relative, str) or not relative or ':' in relative or '\\' in relative
            or relative != str(PurePosixPath(relative)) or PurePosixPath(relative).is_absolute()
            or '..' in PurePosixPath(relative).parts):
        raise NativeExportError('字体资源必须是项目内的相对路径。')
    target = Path(root)
    for part in PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise NativeExportError('font resource symlinks are not supported')
    if not target.is_file() or target.suffix.lower() not in ('.ttf', '.otf'):
        raise NativeExportError('missing local TTF/OTF resource: ' + relative)
    return target


def read_font(path):
    with Path(path).open('rb') as stream:
        data = stream.read(FONT_LIMIT + 1)
    if len(data) > FONT_LIMIT:
        raise NativeExportError('字体文件超过 32 MiB。')
    return data


@lru_cache(maxsize=128)
def _font_metadata(path, stamp, size):
    return font_info(read_font(path))


@dataclass
class FontResource:
    family: str
    src: str
    path: Path
    weight: int
    style: str
    info: dict
    role: str = 'text'
    notice: Path | None = None

    @property
    def variant(self):
        return ('boldItalic' if self.style == 'italic' else 'bold') if self.weight == 700 else ('italic' if self.style == 'italic' else 'regular')

    def public(self):
        return dict(family=self.family, src=self.src, weight=self.weight, style=self.style,
                    role=self.role, bytes=self.path.stat().st_size, license=self.info['license'], licenseUrl=self.info['licenseUrl'])


def project_fonts(root, entries):
    if entries is None:
        return []
    if not isinstance(entries, list) or len(entries) > 64:
        raise NativeExportError('customFonts must contain at most 64 font faces')
    result, keys, total = [], set(), 0
    for entry in entries:
        fields(entry, 'family src weight style license role', 'customFonts')
        family = string(entry.get('family'), 'font family')
        path = local_font_path(root, entry.get('src'))
        stamp = path.stat()
        total += stamp.st_size
        if total > FONT_TOTAL_LIMIT:
            raise NativeExportError('project fonts exceed 100 MiB')
        info = _font_metadata(str(path), stamp.st_mtime_ns, stamp.st_size)
        require_editable(info)
        role = entry.get('role', 'text')
        if role not in ('text', 'math'):
            raise NativeExportError('project font role must be text or math')
        if role == 'math' and not info.get('math'):
            raise NativeExportError('math font requires an OpenType MATH table')
        if family not in info['aliases']:
            raise NativeExportError('font family does not match resource: ' + family)
        weight, style = (700 if info['bold'] else 400), ('italic' if info['italic'] else 'normal')
        if entry.get('weight', weight) != weight or entry.get('style', style) != style:
            raise NativeExportError('font weight/style does not match resource: ' + family)
        key = (family, weight, style)
        if key in keys:
            raise NativeExportError('duplicate project font face: ' + family)
        keys.add(key)
        notice_path = None
        if 'license' in entry:
            # License notices travel with the portable project, without loading
            # them as executable content or following external URLs.
            notice = entry['license']
            if not isinstance(notice, str) or not notice or ':' in notice or '\\' in notice or '..' in PurePosixPath(notice).parts or PurePosixPath(notice).is_absolute() or notice != str(PurePosixPath(notice)):
                raise NativeExportError('font license must be a project-relative notice file')
            notice_path = Path(root)
            for part in PurePosixPath(notice).parts:
                notice_path = notice_path / part
                if notice_path.is_symlink():raise NativeExportError('font notice symlinks are not supported')
            if not notice_path.is_file() or notice_path.stat().st_size > 1024 * 1024:
                raise NativeExportError('missing or oversized font license notice')
        result.append(FontResource(family, entry['src'], path, weight, style, info, role, notice_path))
    return result


def make_eot(data):
    """Full, uncompressed EOT v2.1. No subsetting or permission-bit changes."""
    info = font_info(data)
    require_editable(info)
    header = struct.pack('<4I10sBBIHH4I2II4IH', 0, len(data), 0x20001, 0,
                         info['panose'], 1, int(info['italic']), info['weight'], info['rights'], 0x504C,
                         *info['unicodeRanges'], *info['codePageRanges'], info['checksum'], 0, 0, 0, 0, 0)
    names = b''
    for value in (info['eotFamily'], info['eotStyle'], info['versionName'], info['fullName']):
        encoded = value.encode('utf-16-le')
        names += struct.pack('<H', len(encoded)) + encoded + b'\0\0'
    names += b'\0\0'  # RootStringSize = 0 (document font, no web root restriction).
    result = bytearray(header + names + data)
    struct.pack_into('<I', result, 0, len(result))
    return bytes(result)


def read_eot(data):
    """Validate our uncompressed EOT structure and return the original SFNT."""
    if not 94 <= len(data) <= FONT_LIMIT + 40000:
        raise NativeExportError('invalid embedded font length')
    size, length, version, flags = struct.unpack_from('<4I', data)
    if size != len(data) or version != 0x20001 or flags != 0 or struct.unpack_from('<H', data, 34)[0] != 0x504C:
        raise NativeExportError('invalid uncompressed EOT header')
    offset = 82
    for _ in range(4):
        if offset + 2 > len(data):
            raise NativeExportError('truncated embedded font name')
        n = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        if n % 2 or offset + n + 2 > len(data) or data[offset + n:offset + n + 2] != b'\0\0':
            raise NativeExportError('invalid embedded font name/padding')
        try:
            data[offset:offset + n].decode('utf-16-le')
        except UnicodeError as exc:
            raise NativeExportError('invalid embedded font name') from exc
        offset += n + 2
    if data[offset:offset + 2] != b'\0\0' or offset + 2 + length != len(data):
        raise NativeExportError('embedded font payload length mismatch')
    font = data[offset + 2:]
    info = font_info(font)
    require_editable(info)
    if struct.unpack_from('<H', data, 32)[0] != info['rights']:
        raise NativeExportError('embedded font permission mismatch')
    return font


def embed_project_fonts(package, presentation, resources):
    """Embed every explicitly emitted text family/style, failing on gaps."""
    available = {(resource.family, resource.variant): resource for resource in resources}
    math_families = {resource.family for resource in resources if resource.role == 'math'}
    used = set()
    for name, data in list(package.parts.items()):
        if not name.endswith('.xml') or not name.startswith(('ppt/slides/', 'ppt/charts/')):
            continue
        doc = ET.fromstring(data)
        for props in doc.iter():
            if props.tag not in ('{' + NS['a'] + '}' + key for key in ('rPr', 'defRPr', 'endParaRPr')):
                continue
            bold, italic = props.get('b') == '1', props.get('i') == '1'
            variant = 'boldItalic' if bold and italic else 'bold' if bold else 'italic' if italic else 'regular'
            for child in props:
                if child.tag in ('{' + NS['a'] + '}' + key for key in ('latin', 'ea', 'cs')):
                    family = child.get('typeface')
                    used.add((family, 'regular' if family in math_families else variant))
    missing = used - set(available)
    if missing:
        raise NativeExportError('缺少项目字体资源：' + '、'.join(f'{family}/{variant}' for family, variant in sorted(missing)) + '。请添加对应字体文件，或关闭嵌入字体。')
    if not used:
        raise NativeExportError('没有可嵌入的文本字体。')
    presentation.set('embedTrueTypeFonts', '1')
    presentation.set('saveSubsetFonts', '0')
    font_list = node('p:embeddedFontLst', presentation)
    for family in sorted({family for family, _ in used}):
        item = node('p:embeddedFont', font_list)
        node('p:font', item, typeface=family, charset='0')
        # Store all supplied faces of a used family to retain future editability.
        for variant in ('regular', 'bold', 'italic', 'boldItalic'):
            resource = available.get((family, variant))
            if resource is None:
                continue
            part = f'ppt/fonts/font{1 + sum(name.startswith("ppt/fonts/") for name in package.parts)}.fntdata'
            package.add(part, make_eot(read_font(resource.path)), 'application/x-fontdata')
            rid = package.relate('ppt/presentation.xml', part.removeprefix('ppt/'), 'font')
            node('p:' + variant, item, **{'r:id': rid})
    notices = {}
    for resource in resources:
        if resource.family in {family for family, _ in used} and resource.notice:
            notices.setdefault(resource.notice, set()).add(resource.family)
    for index, (path, families) in enumerate(sorted(notices.items(), key=lambda item: str(item[0])), 1):
        notice = ET.Element('{urn:pptd:font-license}fontLicense', families=', '.join(sorted(families)))
        ET.SubElement(notice, '{urn:pptd:font-license}notice').text = path.read_text(encoding='utf-8')
        part = f'customXml/fontLicense{index}.xml'
        package.add(part, notice, 'application/xml')
        package.relate('ppt/presentation.xml', '../' + part, 'customXml')
