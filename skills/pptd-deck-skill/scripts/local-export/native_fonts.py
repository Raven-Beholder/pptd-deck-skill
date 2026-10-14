"""Read installed SFNT family names without loading or redistributing fonts.

Only the name table is read, with bounded file/table counts and byte ranges.
No font library, shell command, download, or persistent font cache is used.
"""
from pathlib import Path
import os
import struct


def families(path):
    result = set()
    with Path(path).open('rb') as stream:
        size = stream.seek(0, 2)
        def read(offset, length):
            if offset < 0 or length < 0 or offset + length > size:
                raise ValueError('font table outside file')
            stream.seek(offset)
            data = stream.read(length)
            if len(data) != length:
                raise ValueError('incomplete font table')
            return data
        header = read(0, 12)
        if header[:4] == b'ttcf':
            count = struct.unpack('>I', header[8:12])[0]
            if not 1 <= count <= 128:
                raise ValueError('font collection exceeds inventory limit')
            offsets = struct.unpack('>' + 'I' * count, read(12, count * 4))
        else:
            offsets = (0,)
        for offset in offsets:
            header = read(offset, 12)
            if header[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'true'):
                continue
            count = struct.unpack('>H', header[4:6])[0]
            if count > 128:
                continue
            records = read(offset + 12, count * 16)
            for tag, _, table_offset, length in struct.iter_unpack('>4sIII', records):
                if tag != b'name' or not 6 <= length <= 1024 * 1024:
                    continue
                data = read(table_offset, length)
                _, names, storage = struct.unpack('>HHH', data[:6])
                if names > 4096 or 6 + names * 12 > len(data):
                    continue
                for platform, encoding, _, identifier, n, start in struct.iter_unpack('>HHHHHH', data[6:6 + names * 12]):
                    if identifier not in (1, 16) or not 0 < n <= 512 or storage + start + n > len(data):
                        continue
                    codec = 'utf-16-be' if platform in (0, 3) else 'mac_roman' if platform == 1 and encoding == 0 else None
                    if codec is None:
                        continue
                    try:
                        name = data[storage + start:storage + start + n].decode(codec).strip()
                    except UnicodeError:
                        continue
                    if name and not name.startswith('.') and all(ord(c) >= 32 for c in name):
                        result.add(name)
    return result


def installed_families():
    roots = [Path('/System/Library/Fonts'), Path('/Library/Fonts'), Path.home() / 'Library/Fonts',
             Path('/usr/share/fonts'), Path('/usr/local/share/fonts'), Path.home() / '.local/share/fonts']
    if os.name == 'nt':
        roots = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts',
                 Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Microsoft/Windows/Fonts']
    result, scanned = set(), 0
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*')):
            if path.suffix.lower() not in ('.ttf', '.otf', '.ttc') or not path.is_file():
                continue
            scanned += 1
            if scanned > 1500:
                return sorted(result, key=str.casefold)
            try:
                result.update(families(path))
            except (OSError, ValueError, struct.error):
                continue
    return sorted(result, key=str.casefold)
