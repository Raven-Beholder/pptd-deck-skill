"""Bounded, read-only OOXML template inspection and explicit page acceptance.

This is a reference import, not a lossless PPTX-to-PPTD converter. Original
bytes remain authoritative. No external relationships are fetched or executed.
"""
import hashlib
import json
import os
import posixpath
import shutil
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET

from PIL import Image, ImageChops, ImageDraw, ImageStat
from native_common import NS, project_path

LIMIT = 100 * 1024 * 1024
XML_LIMIT = 8 * 1024 * 1024


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def xml_text(node):
    return ET.tostring(node, encoding='unicode') if node is not None else None


class Package:
    def __init__(self, archive):
        self.archive = archive
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) > 4096 or len(names) != len(set(names)):
            raise ValueError('template ZIP has too many or duplicate entries')
        if sum(entry.file_size for entry in entries) > LIMIT:
            raise ValueError('template ZIP exceeds 100 MiB uncompressed')
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('unsafe template ZIP path')
        self.names = set(names)

    def xml(self, name):
        if name not in self.names:
            raise ValueError(f'missing template part: {name}')
        if self.archive.getinfo(name).file_size > XML_LIMIT:
            raise ValueError('template XML exceeds 8 MiB')
        data = self.archive.read(name)
        if b'<!DOCTYPE' in data.replace(b'\0', b'').upper() or b'<!ENTITY' in data.replace(b'\0', b'').upper():
            raise ValueError('DTD/entities are not allowed in template XML')
        try:
            return ET.fromstring(data)
        except ET.ParseError as error:
            raise ValueError(f'invalid template XML: {name}: {error}') from error

    def rels(self, part):
        name = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
        if name not in self.names:
            return {}
        result = {}
        for rel in self.xml(name):
            identifier = rel.get('Id')
            if not identifier or identifier in result:
                raise ValueError('duplicate or missing relationship id')
            target = rel.get('Target', '')
            external = rel.get('TargetMode') == 'External'
            if not external:
                target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(part), target))
                if target.startswith('../') or '\\' in target or ':' in target or target not in self.names:
                    raise ValueError(f'broken or unsafe template relationship: {part}')
            result[identifier] = {'target': target, 'kind': rel.get('Type', '').rsplit('/', 1)[-1], 'external': external}
        return result

    def related(self, part, kind, required=True):
        matches = [r for r in self.rels(part).values() if r['kind'] == kind]
        if len(matches) != 1 or matches[0]['external']:
            if not matches and not required:
                return None
            raise ValueError(f'{part} needs one internal {kind} relationship')
        return matches[0]['target']


def objects(document, part):
    result = []
    tree = document.find('p:cSld/p:spTree', NS)
    if tree is None:
        raise ValueError(f'missing shape tree: {part}')
    for shape in tree:
        kind = shape.tag.rsplit('}', 1)[-1]
        if kind in ('nvGrpSpPr', 'grpSpPr'):
            continue
        prop = shape.find('.//p:cNvPr', NS)
        ph = shape.find('.//p:ph', NS) if kind != 'grpSp' else None
        xfrm = shape.find('p:spPr/a:xfrm', NS)
        if xfrm is None:
            xfrm = shape.find('p:xfrm', NS)
        bounds = None
        if xfrm is not None:
            off, ext = xfrm.find('a:off', NS), xfrm.find('a:ext', NS)
            if off is not None and ext is not None:
                bounds = [int(off.get('x')), int(off.get('y')), int(ext.get('cx')), int(ext.get('cy'))]
                bounds = [v / 12700 for v in bounds]
        result.append({'id': prop.get('id') if prop is not None else None,
                       'name': prop.get('name', '') if prop is not None else '',
                       'kind': kind, 'placeholder': dict(ph.attrib) if ph is not None else None,
                       'boundsPt': bounds, 'boundsSource': part if bounds else None,
                       'text': '\n'.join(''.join(p.itertext()) for p in shape.findall('.//a:p', NS)),
                       'declaredFonts': sorted({n.get('typeface') for n in shape.iter() if n.get('typeface')}),
                       'declaredFontSizesPt': sorted({int(n.get('sz')) / 100 for n in shape.iter() if n.get('sz')}),
                       'transform': dict(xfrm.attrib) if xfrm is not None else None,
                       'rawXml': xml_text(shape)})
    return result


def inherit_bounds(items, parents, by_type=False):
    for item in items:
        ph = item['placeholder']
        if ph is None or item['boundsPt'] is not None:
            continue
        candidates = [p for p in parents if p['placeholder'] is not None and
                      (p['placeholder'].get('type', 'obj') == ph.get('type', 'obj') if by_type else
                       p['placeholder'].get('idx', '0') == ph.get('idx', '0'))]
        if len(candidates) == 1:
            item['boundsPt'] = candidates[0]['boundsPt']
            item['boundsSource'] = candidates[0]['boundsSource']


def extract(source):
    """Keep declaration order, relationship provenance and unresolved styles."""
    if Path(source).stat().st_size > LIMIT:
        raise ValueError('template source exceeds 100 MiB')
    try:
        with ZipFile(source) as archive:
            package = Package(archive)
            presentation = package.related('', 'officeDocument')
            doc = package.xml(presentation)
            size = doc.find('p:sldSz', NS)
            if size is None:
                raise ValueError('template slide size is missing')
            size = [int(size.get(k)) / 12700 for k in ('cx', 'cy')]
            if any(v <= 0 for v in size):
                raise ValueError('invalid template slide size')
            rels = package.rels(presentation)
            slides, layouts, masters, themes = [], {}, {}, {}

            def inspect(part):
                document = package.xml(part)
                common = document.find('p:cSld', NS)
                if common is None:
                    raise ValueError(f'missing slide content: {part}')
                return {'part': part, 'name': common.get('name', ''),
                        'objects': objects(document, part),
                        'backgroundXml': xml_text(document.find('p:cSld/p:bg', NS)),
                        'textStylesXml': xml_text(document.find('p:txStyles', NS)),
                        'attributes': dict(document.attrib),
                        'colorMapXml': xml_text(document.find('p:clrMap', NS)),
                        'colorMapOverrideXml': xml_text(document.find('p:clrMapOvr', NS))}

            def master(part):
                if part not in masters:
                    masters[part] = inspect(part)
                    theme = package.related(part, 'theme')
                    masters[part]['theme'] = theme
                    theme_doc = package.xml(theme)
                    colors = theme_doc.find('a:themeElements/a:clrScheme', NS)
                    themes[theme] = {'part': theme, 'rawXml': xml_text(theme_doc),
                                     'colors': {n.tag.rsplit('}', 1)[-1]: dict(n[0].attrib) for n in colors if len(n)} if colors is not None else {},
                                     'fonts': sorted({n.get('typeface') for n in theme_doc.iter() if n.get('typeface')})}
                return masters[part]

            def layout(part):
                if part not in layouts:
                    record = inspect(part)
                    parent = master(package.related(part, 'slideMaster'))
                    inherit_bounds(record['objects'], parent['objects'], by_type=True)
                    record['master'] = parent['part']
                    layouts[part] = record
                return layouts[part]

            # Include unused layouts too: they are reusable template designs.
            for entry in doc.findall('p:sldMasterIdLst/p:sldMasterId', NS):
                rel = rels.get(entry.get('{%s}id' % NS['r']))
                if not rel or rel['external'] or rel['kind'] != 'slideMaster':
                    raise ValueError('invalid presentation master relationship')
                master(rel['target'])
                for r in package.rels(rel['target']).values():
                    if r['kind'] == 'slideLayout' and not r['external']:
                        layout(r['target'])
            for index, entry in enumerate(doc.findall('p:sldIdLst/p:sldId', NS), 1):
                rel = rels.get(entry.get('{%s}id' % NS['r']))
                if not rel or rel['external'] or rel['kind'] != 'slide':
                    raise ValueError('invalid presentation slide relationship')
                part = rel['target']
                record = inspect(part)
                parent = layout(package.related(part, 'slideLayout'))
                inherit_bounds(record['objects'], parent['objects'])
                record.update(page=index, layout=parent['part'], hidden=record['attributes'].get('show') == '0')
                slides.append(record)
            if not slides:
                raise ValueError('template has no reference slides; add sample slides before import')
            return {'version': 1, 'sizePt': size, 'slides': slides, 'layouts': list(layouts.values()),
                    'masters': list(masters.values()), 'themes': list(themes.values()),
                    'limitations': ['Reference extraction only; no editable conversion or Office rendering.',
                                    'Only placeholder bounds are inherited. Text/fill/theme style XML is evidence, not flattened styling.',
                                    'Groups, charts, SmartArt, effects, rotations and external resources require manual reconstruction and visual review.',
                                    'Backgrounds, master visibility and color-map overrides must be interpreted using the retained XML and reference images.']}
    except (BadZipFile, RuntimeError) as error:
        raise ValueError(f'invalid template package: {error}') from error


def image_info(path):
    with Image.open(path) as image:
        if image.format not in ('PNG', 'JPEG') or image.width * image.height > 20_000_000:
            raise ValueError('reference must be a PNG/JPEG with at most 20 million pixels')
        image.load()
        return image.size


def check_mapping(mapping, pages, source_count):
    if not isinstance(mapping, list) or len(mapping) != len(pages):
        raise ValueError('template mapping must cover every project page exactly once')
    if any(not isinstance(m, dict) or set(m) != {'page', 'sourcePage'} or
           m['page'] != pages[i] or type(m['sourcePage']) is not int or
           not 1 <= m['sourcePage'] <= source_count for i, m in enumerate(mapping)):
        raise ValueError('template mapping must follow manifest page paths and valid sourcePage numbers')


def import_template(root, pages, source, references, mapping=None):
    root, source, references = Path(root), Path(source), Path(references)
    if source.suffix.lower() not in ('.pptx', '.potx'):
        raise ValueError('template source must be .pptx or .potx')
    if source.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('template source exceeds portable 20 MiB per-file limit')
    if (root / 'template.json').exists():
        raise ValueError('template already bound; preserve it and use a new project for another import')
    layout = extract(source)
    refs = read(references)
    if (not isinstance(refs, dict) or not isinstance(refs.get('renderer'), str) or not refs['renderer'].strip()
            or not isinstance(refs.get('pages'), list) or len(refs['pages']) != len(layout['slides'])):
        raise ValueError('references need renderer provenance and one image per source slide in presentation order')
    if mapping is None:
        mapping = [{'page': p, 'sourcePage': i} for i, p in enumerate(pages, 1)]
        if len(pages) != len(layout['slides']):
            raise ValueError('different page counts require an explicit --mapping file')
    check_mapping(mapping, pages, len(layout['slides']))
    bundle = 'template/' + uuid.uuid4().hex
    destination = (root / bundle).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError('template directory must stay inside the project')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.template-import-', dir=root) as temp:
        staging = Path(temp)
        source_name = 'source' + source.suffix.lower()
        shutil.copyfile(source, staging / source_name)
        if digest(source) != digest(staging / source_name):
            raise ValueError('template source changed during import')
        # Extract the preserved bytes, not a potentially changed original.
        layout = extract(staging / source_name)
        if len(refs['pages']) != len(layout['slides']):
            raise ValueError('template source changed during import')
        write(staging / 'layouts.json', layout)
        records = []
        for index, name in enumerate(refs['pages'], 1):
            if not isinstance(name, str):
                raise ValueError('reference page paths must be strings')
            path = project_path(references.resolve().parent, name)
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('reference image exceeds 20 MiB')
            target = staging / f'{index:04}.png'
            # Normalize pixels, retain submitted bytes separately for provenance.
            original = staging / f'{index:04}.original'
            shutil.copyfile(path, original)
            dimensions = image_info(original)
            if abs(dimensions[0] / dimensions[1] / (layout['sizePt'][0] / layout['sizePt'][1]) - 1) > .01:
                raise ValueError(f'reference page {index} aspect ratio differs from template')
            with Image.open(original) as image:
                rgba = image.convert('RGBA')
                Image.alpha_composite(Image.new('RGBA', image.size, 'white'), rgba).convert('RGB').save(target)
            records.append({'page': index, 'image': bundle + '/' + target.name,
                            'original': bundle + '/' + original.name})
        if any(p.stat().st_size > 20 * 1024 * 1024 for p in staging.iterdir()) or sum(p.stat().st_size for p in staging.iterdir()) > LIMIT:
            raise ValueError('template bundle exceeds 20 MiB per file or 100 MiB total')
        files = {bundle + '/' + p.name: digest(p) for p in staging.iterdir()}
        contract = {'version': 1, 'source': bundle + '/' + source_name, 'layouts': bundle + '/layouts.json',
                    'renderer': refs['renderer'], 'references': records, 'mapping': mapping, 'files': files}
        # Publish only after all inputs validate. Existing source/deck files stay intact.
        staging.rename(destination)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root, prefix='.template-contract-', delete=False) as stream:
            pending = Path(stream.name)
            stream.write(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')
        os.link(pending, root / 'template.json')
    except Exception:
        shutil.rmtree(destination)
        raise
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return contract


def inputs(root, pages):
    path = root / 'template.json'
    if not path.exists():
        return {}
    value = read(path)
    if (not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('files'), dict)
            or not value['files'] or not isinstance(value.get('references'), list) or not value['references']):
        raise ValueError('invalid template contract')
    check_mapping(value['mapping'], pages, len(value['references']))
    required = {value['source'], value['layouts']}
    for index, ref in enumerate(value['references'], 1):
        if not isinstance(ref, dict) or ref.get('page') != index:
            raise ValueError('reference pages must be in presentation order')
        required.update([ref['image'], ref['original']])
    if required != set(value['files']):
        raise ValueError('template file inventory is incomplete')
    result = {'template.json': digest(path)}
    for name, expected in value['files'].items():
        if not isinstance(name, str) or not name.startswith('template/'):
            raise ValueError('template assets must stay in template/')
        actual = digest(project_path(root, name))
        if actual != expected:
            raise ValueError(f'template input changed: {name}; restore the imported reference')
        result[name] = actual
    return result


def compare(root, deck, report):
    """Build labeled pairs and difference images; metrics never imply acceptance."""
    contract = read(root / 'template.json')
    if report['mode'] != 'layout-proof':
        raise ValueError('template acceptance requires rendered pages; structural mode cannot pass it')
    layout = read(project_path(root, contract['layouts']))
    if abs(deck['size'][0] / deck['size'][1] / (layout['sizePt'][0] / layout['sizePt'][1]) - 1) > .01:
        raise ValueError('project aspect ratio differs from template; fix the page size')
    directory = root / '.pipeline/template'
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for index, mapping in enumerate(contract['mapping']):
        ref = contract['references'][mapping['sourcePage'] - 1]
        with Image.open(project_path(root, ref['image'])) as image:
            reference = image.convert('RGB')
        with Image.open(project_path(root, report['pages'][index]['image'])) as image:
            actual = image.convert('RGB')
        reference.thumbnail((960, 960))
        actual = actual.resize(reference.size, Image.Resampling.LANCZOS)
        diff = ImageChops.difference(reference, actual)
        width, height = reference.size
        pair = Image.new('RGB', (width * 2, height + 30), 'white')
        pair.paste(reference, (0, 30)); pair.paste(actual, (width, 30))
        draw = ImageDraw.Draw(pair)
        draw.text((8, 8), f'Template P{mapping["sourcePage"]}', fill='black')
        draw.text((width + 8, 8), f'Candidate P{index + 1} (Pillow)', fill='black')
        pair_path, diff_path = directory / f'{index + 1:04}-pair.png', directory / f'{index + 1:04}-diff.png'
        pair.save(pair_path); diff.save(diff_path)
        records.append({'number': index + 1, **mapping,
                        'pair': pair_path.relative_to(root).as_posix(), 'pairSha256': digest(pair_path),
                        'diff': diff_path.relative_to(root).as_posix(), 'diffSha256': digest(diff_path),
                        'meanAbsolutePixelError': sum(ImageStat.Stat(diff).mean) / (3 * 255)})
    return {'version': 1, 'referenceRenderer': contract['renderer'], 'pages': records,
            'metricPurpose': 'Navigation only. Content edits, font rasterization and renderer differences change pixels.',
            'officeRenderVerified': False}


def verify_comparison(root, report):
    comparison = report.get('templateComparison')
    if not comparison:
        raise ValueError('template comparison missing; rerun prepare')
    contract = read(root / 'template.json')
    if [(p['page'], p['sourcePage']) for p in comparison['pages']] != [(p['page'], p['sourcePage']) for p in contract['mapping']]:
        raise ValueError('template comparison mapping is stale')
    for record in comparison['pages']:
        for name in ('pair', 'diff'):
            if digest(project_path(root, record[name])) != record[name + 'Sha256']:
                raise ValueError('template comparison image changed; rerun prepare and review')


def decisions(value, comparison):
    expected = [(r['page'], r['sourcePage']) for r in comparison['pages']]
    if not isinstance(value, list) or len(value) != len(expected):
        raise ValueError('template decisions must cover every mapped page')
    for record, key in zip(value, expected):
        if (not isinstance(record, dict) or (record.get('page'), record.get('sourcePage')) != key or
                type(record.get('passed')) is not bool or not isinstance(record.get('note'), str) or not record['note'].strip()):
            raise ValueError('template decisions need matching page/sourcePage, boolean passed and a concrete note')
    return all(record['passed'] for record in value)
