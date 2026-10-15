"""Offline QA font selection. Inspect metadata and coverage, never guess paths."""
import struct

from font_support import face, alphabet
from native_fonts import font_faces, installed_paths
from native_math import Formula
from native_text import RichText
from native_project_fonts import project_fonts, declared_font_defaults
from native_table import grid, resolve_table_style, cell_style

BODY_ORDER = ('Source Han Sans SC', 'Noto Sans CJK SC', 'Noto Sans SC', 'PingFang SC',
              'Microsoft YaHei', 'Hiragino Sans GB', 'Arial Unicode MS', 'DejaVu Sans',
              'Liberation Sans', 'Arial')
MATH_ORDER = ('STIX Two Math', 'Cambria Math', 'STIXGeneral', 'DejaVu Sans', 'Arial Unicode MS')


def inventory(roots=None):
    records = []
    for path in installed_paths(roots):
        try:
            records.extend(dict(item, path=str(path)) for item in font_faces(path))
        except (OSError, ValueError, struct.error):
            continue
    return records


def covered(item, text):
    try:
        font = face(item['path'], item['index'])
        return all(font.supports(char) for char in set(text))
    except (OSError, ValueError, KeyError, struct.error):
        return False


def select(records, text, preferred=None, math=False):
    order = MATH_ORDER if math else BODY_ORDER
    def rank(item):
        aliases = item['aliases']
        preference = 0 if preferred in aliases else 1
        position = min((order.index(name) for name in aliases if name in order), default=len(order))
        return preference, int(math and not item['math']), int(item['bold'] or item['italic']), position, item['family'], item['path'], item['index']
    for item in sorted((item for item in records if not item['bold'] and not item['italic']), key=rank):
        if covered(item, text):
            return dict(item, family=preferred if preferred in item['aliases'] else item['family'])
    codes = ', '.join(f'U+{ord(c):04X}' for c in sorted(set(text)) if not c.isspace())
    raise ValueError('no installed font covers the required text (' + codes[:180] +
                     '); add a suitable project font or provide an explicit mapping')


def mapping(item, records, text):
    result = {'regular': {'path': item['path'], 'index': item['index']}, 'syntheticStyles': True}
    for variant, bold, italic in [('bold', True, False), ('italic', False, True), ('boldItalic', True, True)]:
        matches = [record for record in records if item['family'] in record['aliases'] and
                   record['bold'] == bold and record['italic'] == italic and covered(record, text)]
        if matches:
            chosen = sorted(matches, key=lambda r: (r['path'], r['index']))[0]
            result[variant] = {'path': chosen['path'], 'index': chosen['index']}
    return result


def defaults(text, preferred=None, roots=None):
    records = inventory(roots)
    body = select(records, text or 'ABC 123', preferred)
    math = select(records, 'x+1=2', math=True)
    return body['family'], {'families': {body['family']: mapping(body, records, text)},
                            'math': mapping(math, records, 'x+1=2')}


def requirements(deck, pages, default):
    """Collect effective text, including rich text, table styles and math alphabets."""
    needed, mathematical = {}, []
    theme = deck.get('theme', {})
    def formula(node, family, variant=None):
        variant = node.value if node.kind == 'style' else variant
        if node.kind == 'text':
            needed.setdefault(family, []).append(node.value)
        elif node.kind in ('symbol', 'upright'):
            mathematical.append(alphabet(node.value, variant))
        for child in node.children:
            formula(child, family, variant)
    def text(content, table_default=None):
        style = dict(fontFamily=table_default or default, fontSize=16, bold=False, italic=False)
        reference = content.get('style', '')
        if reference.startswith('$'):
            style.update(theme.get('textStyles', {}).get(reference[1:], {}))
        style.update(content)
        for _, runs in RichText(content.get('text', ''), style).paragraphs:
            for value, run in runs:
                if isinstance(value, Formula):
                    formula(value.expression, run['fontFamily'])
                elif value is not None:
                    family = run['fontFamily']
                    if not isinstance(family, str):
                        raise ValueError('automatic QA mapping requires one multilingual fontFamily per text run')
                    needed.setdefault(family, []).append(value)
    for page in pages:
        for element in page['elements']:
            if element['elementType'] == 'text':
                text(element['content'])
            elif element['elementType'] == 'table':
                h, w = len(element['rowHeights']), len(element['columnWidths'])
                cells = grid(element['rows'], h, w)
                table_style = resolve_table_style(element, theme)
                for (r, c), (ar, ac, _, _, cell) in cells.items():
                    if (r, c) == (ar, ac):
                        style = cell_style(element, table_style, cell, r, c, h, w, theme,
                                           default_font=default if deck.get('customFonts') else None)
                        text(dict(style, text=cell.get('text', '')))
    return {family: ''.join(values) for family, values in needed.items()}, ''.join(mathematical)


def configure(root, deck, pages, roots=None):
    """Preserve declared families. Missing families produce an actionable error."""
    resources = project_fonts(root, deck.get('customFonts'), allow_missing=True)
    config = {'families': {}}
    for resource in resources:
        target = config.setdefault('math', {}) if resource.role == 'math' else config['families'].setdefault(resource.family, {})
        target[resource.variant] = resource.src
        if resource.role == 'math':
            target['syntheticStyles'] = True
    default, _ = declared_font_defaults(deck.get('customFonts'), resources)
    needed, math_text = requirements(deck, pages, default)
    records = None
    for family, text in needed.items():
        if family in config['families']:
            continue
        if records is None:
            records = inventory(roots)
        chosen = select(records, text, family)
        if family not in chosen['aliases']:
            raise ValueError(f'font family {family!r} is unavailable or lacks required glyphs; '
                             f'available replacement: {chosen["family"]!r}. Change fontFamily deliberately, '
                             'or add the requested project font; no source was changed')
        config['families'][family] = mapping(chosen, records, text)
    if 'math' not in config:
        if records is None:
            records = inventory(roots)
        chosen = select(records, math_text or 'x+1=2', math=True)
        config['math'] = mapping(chosen, records, math_text)
    return config
