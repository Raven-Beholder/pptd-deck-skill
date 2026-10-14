"""Small OOXML primitives. Licensing review: see NATIVE_NOTICE.md."""
import math
import re
import xml.etree.ElementTree as ET

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'a14': 'http://schemas.microsoft.com/office/drawing/2010/main',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    's': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


class NativeExportError(ValueError):
    """Unsupported/invalid input; callers must not silently retry with WASM."""


def node(tag, parent=None, text=None, **attrs):
    prefix, local = tag.split(':')
    element = ET.Element('{%s}%s' % (NS[prefix], local))
    for key, value in attrs.items():
        if ':' in key:
            pre, name = key.split(':')
            key = '{%s}%s' % (NS[pre], name)
        element.set(key, str(value))
    element.text = text
    if parent is not None:
        parent.append(element)
    return element


def xml(element):
    return ET.tostring(element, encoding='utf-8', xml_declaration=True)


def fields(value, allowed, where):
    if not isinstance(value, dict):
        raise NativeExportError(f'{where}: expected mapping')
    unknown = set(value) - set(allowed.split())
    if unknown:
        raise NativeExportError(f'{where}: unsupported field(s): {", ".join(sorted(map(str, unknown)))}')
    return value


def number(value, where, low=None, high=None):
    try:
        finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:  # Python integers need not fit the float geometry calculations.
        finite = False
    if not finite:
        raise NativeExportError(f'{where}: expected finite number')
    if (low is not None and value < low) or (high is not None and value > high):
        raise NativeExportError(f'{where}: value {value} outside [{low}, {high}]')
    return value


def boolean(value, where):
    if not isinstance(value, bool):
        raise NativeExportError(f'{where}: expected boolean')
    return value


def string(value, where):
    if not isinstance(value, str) or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', value):
        raise NativeExportError(f'{where}: expected XML-compatible string')
    return value


def xstring(value):
    """Encode ST_Xstring without turning literal _xHHHH_ text into characters.

    MS-OI29500 22.9.2.19 also requires carriage returns to be encoded; otherwise
    XML parsing normalizes them into line feeds. LF/tab remain literal content.
    """
    return re.sub(r'_x[0-9A-Fa-f]{4}_', lambda m: '_x005F_' + m[0][1:], value).replace('\r', '_x000D_')


def choice(value, choices, where):
    try:
        valid = value in choices
    except TypeError:
        valid = False
    if not valid:
        raise NativeExportError(f'{where}: unsupported value {value!r}; expected {tuple(choices)}')
    return choices[value] if isinstance(choices, dict) else value


def vector(value, length, where, low=None):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise NativeExportError(f'{where}: expected {length} numbers')
    return [number(v, where, low) for v in value]


def emu(value):
    # PPTD defines a logical pixel as one point, not a CSS pixel at 96 DPI.
    return round(number(value * 12700, 'EMU coordinate', -(2 ** 63), 2 ** 63 - 1))


def project_path(root, relative):
    from pathlib import Path
    relative = string(relative, 'resource path')
    if not relative or '\\' in relative or ':' in relative or Path(relative).is_absolute():
        raise NativeExportError(f'only relative project paths are supported: {relative!r}')
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise NativeExportError(f'missing resource or path outside project: {relative}')
    return target


def color(parent, value, theme, opacity=1):
    seen = set()
    while isinstance(value, str) and value.startswith('$'):
        if value in seen or value[1:] not in theme.get('colors', {}):
            raise NativeExportError(f'unknown or cyclic theme color: {value}')
        seen.add(value)
        value = theme['colors'][value[1:]]
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?', value):
        raise NativeExportError(f'expected #RRGGBB or #RRGGBBAA color: {value!r}')
    result = node('a:srgbClr', parent, val=value[1:7].upper())
    alpha = (int(value[7:9], 16) / 255 if len(value) == 9 else 1) * opacity
    if alpha != 1:
        node('a:alpha', result, val=round(alpha * 100000))
    return result


def configure_utf8_console():
    """Windows redirected CLI output must retain Unicode paths and JSON notices."""
    import os
    import sys
    if os.name == 'nt':
        for stream in (sys.stdout,sys.stderr):
            if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
