"""Package integrity and semantic snapshots for exporter comparison.

This is an acceptance aid, not a replacement for Office rendering/playback.
See scripts/local-export/NATIVE_NOTICE.md for provenance/licensing status.
"""
import hashlib
from io import BytesIO
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import unquote

NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
      'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
      'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
      'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
      'a14': 'http://schemas.microsoft.com/office/drawing/2010/main'}
NS.update(c='http://schemas.openxmlformats.org/drawingml/2006/chart',
          s='http://schemas.openxmlformats.org/spreadsheetml/2006/main')


def rels_name(owner):
    return posixpath.join(posixpath.dirname(owner), '_rels', posixpath.basename(owner) + '.rels')


def relationships(archive, owner):
    name = rels_name(owner)
    if name not in archive.namelist():
        return {}
    result = {}
    for rel in ET.fromstring(archive.read(name)):
        rid = rel.get('Id')
        if not rid or rid in result:
            raise ValueError(f'duplicate/missing relationship ID: {name}')
        target = rel.get('Target', '')
        external = rel.get('TargetMode') == 'External'
        if not external:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(owner), unquote(target))).lstrip('/')
            if target not in archive.namelist():
                raise ValueError(f'broken relationship: {name}: {target}')
        result[rid] = dict(target=target, external=external, type=rel.get('Type', '').rsplit('/', 1)[-1])
    return result


def validate_package(archive):
    names = archive.namelist()
    if len(names) != len(set(names)) or archive.testzip():
        raise ValueError('duplicate ZIP entries or CRC error')
    types = ET.fromstring(archive.read('[Content_Types].xml'))
    overrides = {x.get('PartName', '').lstrip('/') for x in types if x.tag.endswith('Override')}
    defaults = {x.get('Extension') for x in types if x.tag.endswith('Default')}
    for name in names:
        if name == '[Content_Types].xml' or name.endswith('/'):
            continue
        if name not in overrides and name.rsplit('.', 1)[-1] not in defaults:
            raise ValueError(f'missing content type: {name}')
        if name.endswith('.rels'):
            base = posixpath.dirname(posixpath.dirname(name))
            owner = posixpath.join(base, posixpath.basename(name)[:-5])
            if name == '_rels/.rels':
                owner = ''
            elif owner not in names:
                raise ValueError(f'relationship owner missing: {name}')
            relationships(archive, owner)
        elif name.endswith('.xml'):
            root = ET.fromstring(archive.read(name))
            rels = relationships(archive, name)
            for element in root.iter():
                for key, value in element.attrib.items():
                    if key.startswith('{' + NS['r'] + '}') and value not in rels:
                        raise ValueError(f'unresolved relationship reference: {name}: {value}')


def tree(element, media=None):
    if element is None:
        return None
    attrs = dict(element.attrib)
    embed = '{' + NS['r'] + '}embed'
    if media is not None and element.tag == '{' + NS['a'] + '}blip' and embed in attrs:
        attrs[embed] = 'sha256:' + media[attrs[embed]]
    if element.tag == '{' + NS['a'] + '}srcRect':
        attrs = {**dict(l='0', t='0', r='0', b='0'), **attrs}
    return [element.tag.rsplit('}', 1)[-1], dict(sorted(attrs.items())),
            element.text or '', [tree(child, media) for child in element]]


def attributes(element, defaults=None):
    return {**(defaults or {}), **({} if element is None else element.attrib)}


def effective_shapes(container):
    """Select the Office 2010 math branch, retaining fallback evidence.

    Unknown compatibility branches must not silently disappear from a parity
    result. This comparator intentionally fails closed outside its vocabulary.
    """
    for shape in container:
        if shape.tag == '{' + NS['mc'] + '}AlternateContent':
            choices = shape.findall('mc:Choice', NS)
            if len(choices) != 1 or choices[0].get('Requires') != 'a14':
                raise ValueError('unsupported AlternateContent branch in semantic comparison')
            fallback = shape.find('mc:Fallback', NS)
            for selected, _ in effective_shapes(choices[0]):
                yield selected, fallback
        else:
            yield shape, None


def decode_xstring(value):
    # One pass is essential: _x005F_x000A_ denotes literal _x000A_.
    return re.sub(r'_x([0-9A-Fa-f]{4})_', lambda m: chr(int(m[1], 16)), value)


def workbook_snapshot(data):
    with zipfile.ZipFile(BytesIO(data)) as archive:
        validate_package(archive)
        main = next(r['target'] for r in relationships(archive, '').values() if r['type'] == 'officeDocument')
        root = ET.fromstring(archive.read(main))
        rels = relationships(archive, main)
        shared = []
        for rel in rels.values():
            if rel['type'] == 'sharedStrings':
                shared = [decode_xstring(''.join(t.text or '' for t in x.findall('.//s:t', NS))) for x in ET.fromstring(archive.read(rel['target']))]
        sheets = []
        for entry in root.findall('s:sheets/s:sheet', NS):
            owner = rels[entry.get('{' + NS['r'] + '}id')]['target']
            cells = {}
            for cell in ET.fromstring(archive.read(owner)).findall('s:sheetData/s:row/s:c', NS):
                ref = cell.get('r')
                if ref in cells:
                    raise ValueError('duplicate workbook cell: ' + ref)
                kind, value = cell.get('t'), cell.findtext('s:v', namespaces=NS)
                if kind == 'inlineStr':
                    value = decode_xstring(''.join(x.text or '' for x in cell.findall('.//s:t', NS)))
                elif kind == 's':
                    value = shared[int(value)]
                elif value is not None and kind not in ('str', 'e', 'b'):
                    value = float(value)
                if cell.find('s:f', NS) is not None:
                    # Formulas are preserved in comparisons, never evaluated.
                    value = dict(formula=cell.findtext('s:f', namespaces=NS), cached=value)
                if value is not None:
                    cells[ref] = value
            sheets.append(dict(name=entry.get('name'), cells=cells))
        return sheets


def formula_cells(formula, sheets):
    match = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", formula)
    if not match or (match[5] is not None and match[3] != match[5]):
        raise ValueError('unsupported chart reference: ' + formula)
    name = (match[1] or match[2]).replace("''", "'")
    sheet = next((s for s in sheets if s['name'] == name), None)
    if sheet is None:
        raise ValueError('chart references missing workbook sheet')
    first, last = int(match[4]), int(match[6] or match[4])
    if not 1 <= first <= last <= 1048576:
        raise ValueError('invalid chart reference range')
    return [sheet['cells'].get(match[3] + str(row)) for row in range(first, last + 1)]


def chart_features(root):
    """Compare data independently of literal/cache/embedded worksheet storage.

    Keep the full XML alongside this view: omitted flags, layout and formatting
    still require review, even when the plotted values agree.
    """
    def flag(parent, path, default=None):
        child = parent.find(path, NS)
        return child.get('val') if child is not None else default

    def points(parent, path, numeric=False):
        data = parent.find(path, NS)
        if data is None:
            return None
        cache = next((child for child in data if child.tag.endswith(('}strLit', '}numLit'))), None)
        if cache is None:
            cache = data.find('c:strRef/c:strCache', NS)
        if cache is None:
            cache = data.find('c:numRef/c:numCache', NS)
        if cache is None:
            raise ValueError('unsupported chart data storage')
        values = [None] * int(cache.find('c:ptCount', NS).get('val'))
        for point in cache.findall('c:pt', NS):
            value = point.findtext('c:v', default='', namespaces=NS)
            values[int(point.get('idx'))] = float(value) if numeric and value != '' else decode_xstring(value)
        return values

    groups, axes = [], []
    plot = root.find('c:chart/c:plotArea', NS)
    for child in plot:
        kind = child.tag.rsplit('}', 1)[-1]
        if kind.endswith('Chart'):
            series = []
            for entry in child.findall('c:ser', NS):
                name = entry.findtext('c:tx/c:v', namespaces=NS)
                if name is None:
                    name = entry.findtext('c:tx/c:strRef/c:strCache/c:pt/c:v', namespaces=NS)
                series.append(dict(name=decode_xstring(name) if name is not None else None, categories=points(entry, 'c:cat'), values=points(entry, 'c:val', True),
                                   numberFormat=entry.findtext('.//c:formatCode', namespaces=NS),
                                   smooth=flag(entry, 'c:smooth', '0'),
                                   marker=flag(entry, 'c:marker/c:symbol', 'auto')))
            groups.append(dict(kind=kind, direction=flag(child, 'c:barDir'),
                               grouping=flag(child, 'c:grouping'), series=series,
                               holeSize=flag(child, 'c:holeSize'), gapWidth=flag(child, 'c:gapWidth'),
                               overlap=flag(child, 'c:overlap'), firstSliceAngle=flag(child, 'c:firstSliceAng')))
        elif kind in ('catAx', 'valAx'):
            axes.append(dict(kind=kind, position=flag(child, 'c:axPos'),
                             orientation=flag(child, 'c:scaling/c:orientation', 'minMax'),
                             min=flag(child, 'c:scaling/c:min'), max=flag(child, 'c:scaling/c:max'),
                             hidden=flag(child, 'c:delete', '0'), numberFormat=attributes(child.find('c:numFmt', NS)),
                             majorGridlines=child.find('c:majorGridlines', NS) is not None))
    return dict(groups=groups, axes=axes, blanks=flag(root, 'c:chart/c:dispBlanksAs', 'gap'))


def chart_snapshot(archive, owner):
    root = ET.fromstring(archive.read(owner))
    rels = relationships(archive, owner)
    external = root.find('c:externalData', NS)
    if external is None:
        # The legacy oracle writes inline literals, without editable XLSX.
        # Preserve that capability difference instead of rejecting comparison.
        if root.findall('.//c:numRef', NS) or root.findall('.//c:strRef', NS):
            raise ValueError('chart references worksheet data without a workbook relationship')
        for cache in [*root.findall('.//c:numLit', NS), *root.findall('.//c:strLit', NS)]:
            count = int(cache.find('c:ptCount', NS).get('val'))
            indices = [int(p.get('idx')) for p in cache.findall('c:pt', NS)]
            if len(indices) != len(set(indices)) or any(i < 0 or i >= count for i in indices):
                raise ValueError('invalid literal chart data points')
        return dict(features=chart_features(root), xml=tree(root), workbook=None, editableWorkbook=False)
    key = '{' + NS['r'] + '}id'
    rel = rels[external.get(key)]
    if rel['external'] or rel['type'] != 'package':
        raise ValueError('chart data must be an embedded workbook package')
    sheets = workbook_snapshot(archive.read(rel['target']))
    for reference in [*root.findall('.//c:numRef', NS), *root.findall('.//c:strRef', NS)]:
        numeric = reference.tag.endswith('}numRef')
        values = formula_cells(reference.findtext('c:f', namespaces=NS), sheets)
        cache = reference.find('c:numCache' if numeric else 'c:strCache', NS)
        if cache is None or int(cache.find('c:ptCount', NS).get('val')) != len(values):
            raise ValueError('chart cache count differs from workbook range')
        points = {}
        for point in cache.findall('c:pt', NS):
            index = int(point.get('idx'))
            if index in points or not 0 <= index < len(values):
                raise ValueError('duplicate/out-of-range chart cache point')
            value = point.findtext('c:v', default='', namespaces=NS)
            points[index] = float(value) if numeric and value != '' else decode_xstring(value)
        for index, value in enumerate(values):
            cached = points.get(index)
            if isinstance(value, dict):
                value = value['cached']
            expected = (None if value is None else float(value)) if numeric else ('' if value is None else str(value))
            # Numeric categories stored in XLSX have no redundant .0 suffix.
            if not numeric and isinstance(value, float) and value.is_integer():
                expected = str(int(value))
            if cached != expected and not (value is None and cached is None):
                raise ValueError('chart cache differs from workbook cell at index ' + str(index))
    external.set(key, '$embedded-workbook')
    media = {rid: hashlib.sha256(archive.read(r['target'])).hexdigest()
             for rid, r in rels.items() if r['type'] == 'image' and not r['external']}
    return dict(features=chart_features(root), xml=tree(root, media), workbook=sheets, editableWorkbook=True)


def snapshot(path):
    with zipfile.ZipFile(path) as archive:
        validate_package(archive)
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        rels = relationships(archive, 'ppt/presentation.xml')
        slides = []
        for entry in presentation.findall('p:sldIdLst/p:sldId', NS):
            owner = rels[entry.get('{' + NS['r'] + '}id')]['target']
            slide = ET.fromstring(archive.read(owner))
            slide_rels = relationships(archive, owner)
            media = {rid: hashlib.sha256(archive.read(rel['target'])).hexdigest()
                     for rid, rel in slide_rels.items() if rel['type'] == 'image' and not rel['external']}
            def part_tree(element):
                return tree(element, media)
            shapes = []
            for shape, fallback in effective_shapes(slide.find('p:cSld/p:spTree', NS)):
                if shape.tag.rsplit('}', 1)[-1] in ('nvGrpSpPr', 'grpSpPr'):
                    continue
                if shape.tag not in {'{' + NS['p'] + '}' + kind for kind in ('sp', 'pic', 'cxnSp', 'graphicFrame')}:
                    raise ValueError(f'unsupported shape in semantic comparison: {shape.tag}')
                nv = shape.find('.//p:cNvPr', NS)
                transform = shape.find('p:spPr/a:xfrm', NS)
                if transform is None:
                    transform = shape.find('p:xfrm', NS)
                item = {'name': nv.get('name') if nv is not None else None,
                        'kind': shape.tag.rsplit('}', 1)[-1],
                        'transform': part_tree(transform),
                        'geometry': part_tree(shape.find('p:spPr/a:prstGeom', NS)),
                        'customGeometry': part_tree(shape.find('p:spPr/a:custGeom', NS)),
                        'fill': [part_tree(e) for e in shape.findall('p:spPr/*', NS) if e.tag.endswith(('solidFill', 'gradFill', 'noFill', 'blipFill'))],
                        'border': part_tree(shape.find('p:spPr/a:ln', NS)),
                        'effects': part_tree(shape.find('p:spPr/a:effectLst', NS)),
                        'body': attributes(shape.find('p:txBody/a:bodyPr', NS), dict(anchor='t', vert='horz', rtlCol='0')),
                        'paragraphs': []}
                if fallback is not None:
                    item['alternateFallback'] = part_tree(fallback)
                graphic_data = shape.find('a:graphic/a:graphicData', NS)
                if graphic_data is not None:
                    # Includes the complete table grid, cell text/style/margins
                    # and merge flags. Conservative structural differences are
                    # review items, not automatically rendering regressions.
                    item['graphicData'] = part_tree(graphic_data)
                    chart = graphic_data.find('c:chart', NS)
                    if chart is not None:
                        relation = slide_rels[chart.get('{' + NS['r'] + '}id')]
                        if relation['external'] or relation['type'] != 'chart':
                            raise ValueError('invalid slide chart relationship')
                        item['chart'] = chart_snapshot(archive, relation['target'])
                        # rId/part names may differ without changing behavior.
                        chart.set('{' + NS['r'] + '}id', '$chart')
                        item['graphicData'] = part_tree(graphic_data)
                        item['graphicData'] = part_tree(graphic_data)
                for paragraph in shape.findall('p:txBody/a:p', NS):
                    props = paragraph.find('a:pPr', NS)
                    ps = {'alignment': attributes(props, {'algn': 'l'}),
                          'spacing': [part_tree(c) for c in props] if props is not None else [], 'runs': []}
                    for run in paragraph:
                        if run.tag == '{' + NS['a14'] + '}m':
                            ps['runs'].append({'math': part_tree(run)})
                            continue
                        if run.tag.rsplit('}', 1)[-1] not in ('r', 'br'):
                            continue
                        rp = run.find('a:rPr', NS)
                        attrs = attributes(rp, dict(b='0', i='0', u='none', strike='noStrike', baseline='0', spc='0'))
                        # Proofing language/flags do not affect the tested visual semantics.
                        for key in ('noProof', 'lang', 'dirty'):
                            attrs.pop(key, None)
                        rs = {'text': run.findtext('a:t', default='', namespaces=NS),
                              'break': run.tag.endswith('}br'), 'style': attrs, 'children': []}
                        for child in rp if rp is not None else []:
                            if child.tag.endswith('}hlinkClick'):
                                rs['link'] = slide_rels[child.get('{' + NS['r'] + '}id')]['target']
                            else:
                                rs['children'].append(part_tree(child))
                        ps['runs'].append(rs)
                    item['paragraphs'].append(ps)
                blip = shape.find('p:blipFill/a:blip', NS)
                if blip is not None:
                    target = slide_rels[blip.get('{' + NS['r'] + '}embed')]['target']
                    item['image'] = {'sha256': hashlib.sha256(archive.read(target)).hexdigest(),
                                     'crop': attributes(shape.find('p:blipFill/a:srcRect', NS), dict(l='0', t='0', r='0', b='0')),
                                     'effects': [part_tree(e) for e in blip]}
                shapes.append(item)
            notes = []
            for rel in slide_rels.values():
                if rel['type'] == 'notesSlide':
                    nr = ET.fromstring(archive.read(rel['target']))
                    for shape in nr.findall('.//p:sp', NS):
                        ph = shape.find('p:nvSpPr/p:nvPr/p:ph', NS)
                        if ph is not None and ph.get('type') == 'body':
                            notes.extend(''.join(p.itertext()) for p in shape.findall('p:txBody/a:p', NS))
            slides.append({'shapes': shapes, 'notes': notes,
                           'background': [part_tree(e) for e in slide.findall('p:cSld/p:bg/p:bgPr/*', NS) if not e.tag.endswith('effectLst')],
                           'transition': part_tree(slide.find('p:transition', NS)),
                           'timing': part_tree(slide.find('p:timing', NS)),
                           'math': [part_tree(e) for e in slide.findall('.//m:oMath', NS)]})
        return {'size': attributes(presentation.find('p:sldSz', NS)), 'slides': slides,
                'fonts': sorted(hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('ppt/fonts/'))}


def differences(left, right, path='$'):
    if type(left) is not type(right):
        return [{'path': path, 'legacy': left, 'native': right}]
    if isinstance(left, dict):
        return [d for key in sorted(left.keys() | right.keys()) for d in differences(left.get(key), right.get(key), path + '.' + key)]
    if isinstance(left, list):
        if len(left) != len(right):
            return [{'path': path + '.length', 'legacy': len(left), 'native': len(right)}]
        return [d for index, (a, b) in enumerate(zip(left, right)) for d in differences(a, b, f'{path}[{index}]')]
    return [] if left == right else [{'path': path, 'legacy': left, 'native': right}]
