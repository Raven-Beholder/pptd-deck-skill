"""Compare authored content with the actual OOXML before publication.

This catches dropped elements and text-style fallback. It is not a screenshot
comparison and cannot certify font substitution or appearance inside Office.
"""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import yaml

from native_common import NS, NativeExportError, project_path
from native_text import RichText
from native_math import Formula
from native_table import grid, resolve_table_style, cell_style
from native_project_fonts import project_fonts, declared_font_defaults


def primary(node):
    """Discard compatibility fallbacks so formulas and tables are counted once."""
    if node.tag == '{%s}AlternateContent' % NS['mc']:
        choice = node.find('mc:Choice', NS)
        if choice is None:
            choice = node.find('mc:Fallback', NS)
        if choice is not None:
            return [child for entry in choice for child in primary(entry)]
        return []
    for child in list(node):
        replacements = primary(child)
        if replacements != [child]:
            index = list(node).index(child)
            node.remove(child)
            for replacement in replacements:
                node.insert(index, replacement)
                index += 1
    return [node]


def signature(style):
    family = style['fontFamily']
    latin, east = (family['latin'], family['ea']) if isinstance(family, dict) else (family, family)
    return round(style['fontSize'] * 100), bool(style.get('bold')), bool(style.get('italic')), latin, east


def expected_text(content, theme, default):
    style = dict(fontSize=16, fontFamily=default, bold=False, italic=False)
    if content.get('style', '').startswith('$'):
        style.update(theme.get('textStyles', {}).get(content['style'][1:], {}))
    style.update(content)
    characters, maths = [], 0
    for _, runs in RichText(content.get('text', ''), style).paragraphs:
        for text, effective in runs:
            if isinstance(text, Formula):
                maths += 1
            elif text is not None:
                characters.extend((char, signature(effective)) for char in text.replace('\r', '\n'))
    return characters, maths


def actual_text(shape):
    characters = []
    for run in shape.findall('.//a:r', NS):
        text = run.findtext('a:t', default='', namespaces=NS)
        props = run.find('a:rPr', NS)
        if not text:
            continue
        if props is None:
            raise NativeExportError('export audit: text lost explicit run properties')
        latin, east = props.find('a:latin', NS), props.find('a:ea', NS)
        sig = (int(props.get('sz', '0')), props.get('b') in ('1', 'true'),
               props.get('i') in ('1', 'true'), latin.get('typeface') if latin is not None else None,
               east.get('typeface') if east is not None else None)
        characters.extend((char, sig) for char in text)
    return characters, len(shape.findall('.//m:oMath', NS))


def verify_content(manifest, pptx):
    manifest = Path(manifest)
    root = manifest.parent
    deck = yaml.safe_load(manifest.read_text(encoding='utf-8'))
    theme = deck.get('theme', {})
    resources = project_fonts(root, deck.get('customFonts'), allow_missing=True)
    default, _ = declared_font_defaults(deck.get('customFonts'), resources)
    results = []
    with ZipFile(pptx) as archive:
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))}
        ordered = presentation.findall('p:sldIdLst/p:sldId', NS)
        if len(ordered) != len(deck['pages']):
            raise NativeExportError('export audit: slide count differs from source')
        for page_index, (path, entry) in enumerate(zip(deck['pages'], ordered), 1):
            page = yaml.safe_load(project_path(root, path).read_text(encoding='utf-8'))
            target = rels[entry.get('{%s}id' % NS['r'])]
            # The native writer emits presentation-relative slide targets.
            if not target.startswith('slides/') or '..' in target.split('/'):
                raise NativeExportError('export audit: unexpected slide relationship')
            slide = primary(ET.fromstring(archive.read('ppt/' + target)))[0]
            tree = slide.find('p:cSld/p:spTree', NS)
            shapes = {}
            for shape in tree:
                prop = shape.find('.//p:cNvPr', NS)
                if prop is not None:
                    name = prop.get('name')
                    if name in shapes:
                        raise NativeExportError(f'export audit: page {page_index}: duplicate element name {name!r}')
                    shapes[name] = shape
            text_count = math_count = image_count = 0
            for element in page['elements']:
                identifier = element['elementId']
                where = f'export audit: page {page_index}, element {identifier!r}'
                shape = shapes.get(identifier)
                if shape is None:
                    raise NativeExportError(where + ': element missing; possible blank page')
                expected, expected_maths = [], 0
                kind = element['elementType']
                if kind == 'text':
                    expected, expected_maths = expected_text(element['content'], theme, default)
                elif kind == 'table':
                    h, w = len(element['rowHeights']), len(element['columnWidths'])
                    cells = grid(element['rows'], h, w)
                    style = resolve_table_style(element, theme)
                    for (r, c), (ar, ac, _, _, cell) in sorted(cells.items()):
                        if (r, c) != (ar, ac):
                            continue
                        effective = cell_style(element, style, cell, r, c, h, w, theme,
                                               default_font=default if any(font.get('role', 'text') == 'text' for font in deck.get('customFonts', [])) else None)
                        chars, maths = expected_text(dict(effective, text=cell.get('text', '')), theme, default)
                        expected.extend(chars)
                        expected_maths += maths
                    if shape.find('.//a:tbl', NS) is None:
                        raise NativeExportError(where + ': editable table missing')
                elif kind == 'image':
                    if shape.find('.//a:blip', NS) is None:
                        raise NativeExportError(where + ': image missing')
                    image_count += 1
                elif kind == 'chart' and shape.find('.//c:chart', NS) is None:
                    raise NativeExportError(where + ': editable chart missing')
                if kind in ('text', 'table'):
                    actual, actual_maths = actual_text(shape)
                    if [char for char, _ in expected] != [char for char, _ in actual] or actual_maths != expected_maths:
                        raise NativeExportError(where + ': text/formula content lost or changed; possible blank page')
                    if expected != actual:
                        raise NativeExportError(where + ': font size, bold, italic or family changed; possible style fallback')
                    text_count += len(actual)
                    math_count += actual_maths
            results.append(dict(page=page_index, textCharacters=text_count, mathObjects=math_count,
                                images=image_count, elements=len(page['elements']),
                                blankCandidate=not page['elements']))
    return dict(status='passed', pages=results, blankPages=[p['page'] for p in results if p['blankCandidate']],
                checks=['element-presence', 'text', 'math-count', 'font-size', 'bold', 'italic', 'font-family', 'images', 'tables', 'charts'],
                officeRenderVerified=False)
