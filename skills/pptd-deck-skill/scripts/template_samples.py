"""Create editable starter pages from a bounded subset of a local PPTX/POTX.

Keep original OOXML as evidence. Report every unsupported object/style instead
of claiming a lossless conversion. No browser, Office, network or vendor runtime.
"""
import hashlib
import html
import json
import io
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import yaml
from PIL import Image

import auto_fonts
from template_workflow import Package, extract, digest
from native_common import NS
from native_writer import Writer, SHAPES


def create(source, destination, topic='Template starter', roots=None):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if source.suffix.lower() not in ('.pptx', '.potx'):
        raise ValueError('template source must be .pptx or .potx')
    if destination.exists():
        raise ValueError('template-samples needs a new project directory; existing work is never overwritten')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.template-samples-', dir=destination.parent) as temporary:
        root = Path(temporary) / 'project'
        for name in ('pages', 'media', 'template'):
            (root / name).mkdir(parents=True, exist_ok=True)
        original = root / 'template' / ('source' + source.suffix.lower())
        if source.stat().st_size > 100 * 1024 * 1024:
            raise ValueError('template source exceeds 100 MiB')
        shutil.copyfile(source, original)
        evidence = extract(original)
        (root / 'template/layouts.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        records = auto_fonts.inventory(roots)
        font_config = {'families': {}}
        substitutions, issues, samples = [], [], []
        size = evidence['sizePt']
        if max(size) > 10000:
            raise ValueError('template slide size exceeds 10000 points')

        def family(preferred, text):
            chosen = auto_fonts.select(records, text or 'ABC 123', preferred)
            name = chosen['family']
            if name not in font_config['families']:
                font_config['families'][name] = auto_fonts.mapping(chosen, records, text)
            if preferred and preferred not in chosen['aliases']:
                substitution = {'requested': preferred, 'selected': name}
                if substitution not in substitutions:
                    substitutions.append(substitution)
            return name

        fallback = family(None, topic)
        math = auto_fonts.select(records, 'x+1=2', math=True)
        font_config['math'] = auto_fonts.mapping(math, records, 'x+1=2')
        deck = dict(version='v2', title=topic, size=size,
                    theme={'colors': {}, 'textStyles': {'body': {'fontFamily': fallback, 'fontSize': 18}}}, pages=[])
        layouts = {item['part']: item for item in evidence['layouts']}
        masters = {item['part']: item for item in evidence['masters']}
        themes = {item['part']: ET.fromstring(item['rawXml']) for item in evidence['themes']}

        with ZipFile(original) as archive:
            package = Package(archive)
            for slide in evidence['slides']:
                page_index = slide['page']
                layout = layouts[slide['layout']]
                master = masters[layout['master']]
                theme = themes[master['theme']]
                colors = {}
                for entry in theme.findall('a:themeElements/a:clrScheme/*', NS):
                    if len(entry):
                        colors[entry.tag.rsplit('}', 1)[-1]] = entry[0].get('val') if entry[0].tag.endswith('srgbClr') else entry[0].get('lastClr')
                cmap = ET.fromstring(master['colorMapXml']).attrib if master.get('colorMapXml') else {}
                for layer in (layout, slide):
                    if layer.get('colorMapOverrideXml'):
                        override = ET.fromstring(layer['colorMapOverrideXml']).find('a:overrideClrMapping', NS)
                        if override is not None:
                            cmap = override.attrib

                def issue(item, reason):
                    issues.append(dict(sourcePage=page_index, part=item.get('part', slide['part']),
                                       element=item.get('name', ''), reason=reason))

                def color(parent):
                    if parent is None:
                        return None
                    rgb = parent.find('a:srgbClr', NS)
                    scheme = parent.find('a:schemeClr', NS)
                    system = parent.find('a:sysClr', NS)
                    value = rgb.get('val') if rgb is not None else system.get('lastClr') if system is not None else None
                    if scheme is not None:
                        key = scheme.get('val')
                        value = colors.get(cmap.get(key, key))
                    if not value or len(value) != 6 or any(c not in '0123456789abcdefABCDEF' for c in value):
                        return None
                    if any(len(node) for node in parent):
                        issue({}, 'color transforms need visual reconstruction; base color retained')
                    return '#' + value

                page = {'background': {'type': 'solid', 'color': '#FFFFFF'}, 'elements': []}
                def picture(part, blip_fill, bounds, identifier):
                    blip = blip_fill.find('a:blip', NS)
                    if blip is None:
                        return False
                    relation = package.rels(part).get(blip.get('{%s}embed' % NS['r']))
                    if not relation or relation['external'] or relation['kind'] != 'image':
                        issue({}, 'external or unresolved image was not fetched')
                        return False
                    target = relation['target']
                    if package.archive.getinfo(target).file_size > 20 * 1024 * 1024:
                        raise ValueError('template image exceeds 20 MiB')
                    try:
                        with Image.open(io.BytesIO(archive.read(target))) as image:
                            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 20_000_000:
                                issue({}, 'unsupported or oversized image: ' + target)
                                return False
                            image = image.convert('RGBA')
                    except (OSError, ValueError):
                        issue({}, 'unsupported image: ' + target)
                        return False
                    crop = blip_fill.find('a:srcRect', NS)
                    if crop is not None and any(int(crop.get(k, '0')) for k in ('l', 't', 'r', 'b')):
                        issue({}, 'image crop needs visual reconstruction: ' + target)
                        return False
                    x, y, w, h = bounds
                    # Trim transparent margins, preserving their original placement.
                    bbox = image.getbbox()
                    if bbox is None:
                        return True
                    iw, ih = image.size
                    left, top, right, bottom = bbox
                    x, y, w, h = x + left / iw * w, y + top / ih * h, (right - left) / iw * w, (bottom - top) / ih * h
                    image = image.crop(bbox)
                    if x < 0 or y < 0 or x + w > size[0] or y + h > size[1]:
                        issue({}, 'image outside canvas needs manual placement: ' + target)
                        return False
                    data_name = 'media/' + hashlib.sha256(image.tobytes() + str(image.size).encode()).hexdigest()[:20] + '.png'
                    image.save(root / data_name)
                    page['elements'].append(dict(elementId=identifier, elementType='image', bounds=[x, y, w, h], src=data_name, fit={'mode': 'fill'}))
                    return True

                background = next((layer for layer in (slide, layout, master) if layer.get('backgroundXml')), None)
                if background:
                    bg = ET.fromstring(background['backgroundXml'])
                    solid = color(bg.find('p:bgPr/a:solidFill', NS))
                    blip = bg.find('p:bgPr/a:blipFill', NS)
                    if solid:
                        page['background']['color'] = solid
                    elif blip is not None:
                        picture(background['part'], blip, [0, 0, *size], 'template-background')
                    else:
                        issue(background, 'background reference/gradient needs manual reconstruction')

                for layer in (master, layout, slide):
                    if layer is not slide and slide['attributes'].get('showMasterSp') in ('0', 'false'):
                        continue
                    for object_index, item in enumerate(layer['objects']):
                        if layer is not slide and item['placeholder'] is not None:
                            continue
                        bounds = item['boundsPt']
                        if not bounds or bounds[2] <= 0 or bounds[3] <= 0:
                            issue(dict(item, part=layer['part']), 'missing/unsupported bounds')
                            continue
                        xml = ET.fromstring(item['rawXml'])
                        if xml.find('.//a:xfrm', NS) is not None and any(xml.find('.//a:xfrm', NS).get(k) not in (None, '0', 'false') for k in ('rot', 'flipH', 'flipV')):
                            issue(item, 'rotation/flip needs manual reconstruction')
                            continue
                        identifier = f'{layer["part"].split("/")[-2]}-{object_index}'
                        if item['kind'] == 'pic':
                            blip = xml.find('p:blipFill', NS)
                            if blip is not None:
                                picture(layer['part'], blip, bounds, identifier)
                            continue
                        if item['kind'] != 'sp':
                            issue(item, 'unsupported object: ' + item['kind'])
                            continue
                        if min(bounds[:2]) < 0 or bounds[0] + bounds[2] > size[0] + .01 or bounds[1] + bounds[3] > size[1] + .01:
                            issue(item, 'object extends outside canvas')
                            continue
                        props = xml.find('p:spPr', NS)
                        geometry = props.find('a:prstGeom', NS) if props is not None else None
                        solid = color(props.find('a:solidFill', NS)) if props is not None else None
                        if solid:
                            shape_name = geometry.get('prst') if geometry is not None else 'rect'
                            if shape_name in SHAPES:
                                page['elements'].append(dict(elementId=identifier + '-fill', elementType='shape', bounds=bounds,
                                                             shapeName=shape_name, fill={'type': 'solid', 'color': solid}))
                            else:
                                issue(item, 'unsupported shape: ' + shape_name)
                        if props is not None and any(props.find('a:' + name, NS) is not None for name in ('gradFill', 'blipFill', 'custGeom', 'effectLst', 'ln')):
                            issue(item, 'shape fill/outline/effects need manual reconstruction')
                        paragraphs = []
                        for paragraph in xml.findall('p:txBody/a:p', NS):
                            spans = []
                            for run in paragraph:
                                if run.tag == '{%s}br' % NS['a']:
                                    spans.append('<br>')
                                    continue
                                text = run.findtext('a:t', default='', namespaces=NS)
                                if not text:
                                    continue
                                rp = run.find('a:rPr', NS)
                                default_rp = paragraph.find('a:pPr/a:defRPr', NS)
                                values = dict(default_rp.attrib) if default_rp is not None else {}
                                if rp is not None:
                                    values.update(rp.attrib)
                                font_size = min(4000, max(1, int(values.get('sz', '1800')) / 100))
                                face_node = rp.find('a:ea', NS) if rp is not None else None
                                if face_node is None or not face_node.get('typeface'):
                                    face_node = rp.find('a:latin', NS) if rp is not None else None
                                requested = face_node.get('typeface') if face_node is not None else None
                                if requested and requested.startswith('+'):
                                    role = 'majorFont' if requested.startswith('+mj') else 'minorFont'
                                    themed = theme.find('a:themeElements/a:fontScheme/a:' + role + '/a:latin', NS)
                                    requested = themed.get('typeface') if themed is not None else None
                                selected = family(requested, text)
                                tint = color(rp.find('a:solidFill', NS)) if rp is not None else None
                                css = f'font-size:{font_size:g}px;font-family:{selected};color:{tint or "#252525"};font-weight:{"bold" if values.get("b") in ("1", "true") else "normal"};font-style:{"italic" if values.get("i") in ("1", "true") else "normal"}'
                                spans.append('<span style="' + html.escape(css, quote=True) + '">' + html.escape(text) + '</span>')
                            if spans:
                                alignment = paragraph.find('a:pPr', NS)
                                horizontal = {'l': 'left', 'ctr': 'center', 'r': 'right', 'just': 'justify'}.get(alignment.get('algn') if alignment is not None else None, 'left')
                                paragraphs.append('<p style="text-align:' + horizontal + '">' + ''.join(spans) + '</p>')
                        if paragraphs:
                            body = xml.find('p:txBody/a:bodyPr', NS)
                            vertical = {'ctr': 'middle', 'b': 'bottom'}.get(body.get('anchor') if body is not None else None, 'top')
                            page['elements'].append(dict(elementId=identifier + '-text', elementType='text', bounds=bounds,
                                                         content={'fontFamily': fallback, 'align': ['left', vertical], 'text': ''.join(paragraphs)}))
                            if item['placeholder']:
                                issue(item, 'placeholder text styling is approximate; inherited layout/master styles require review')
                if not page['elements']:
                    issue(slide, 'no supported visible objects; manual reconstruction required')
                filename = f'pages/{page_index:02}.page'
                deck['pages'].append(filename)
                (root / filename).write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding='utf-8')
                samples.append(dict(page=filename, sourcePage=page_index, layout=slide['layout'], hidden=slide['hidden']))
        Writer(dict(deck, pages=[yaml.safe_load((root / p).read_text(encoding='utf-8')) for p in deck['pages']]), root, 'fade').slides()
        (root / 'deck.pptd').write_text(yaml.safe_dump(deck, allow_unicode=True, sort_keys=False), encoding='utf-8')
        report = dict(version=1, status='starter_pages', source='template/' + original.name,
                      sourceSha256=digest(original), samples=samples, fontSubstitutions=substitutions,
                      files={path: digest(root / path) for path in ['template/' + original.name, 'template/layouts.json']},
                      issues=issues, officeRenderVerified=False,
                      limitations=['Editable starter pages, not a lossless PPTX import.',
                                   'Explicit run size/bold/italic/color/alignment are retained; inherited text styles, spacing and insets are approximate.',
                                   'Sample count follows source slides, not the required final deck length.',
                                   'Inspect source/reference images and every generated page before use.'])
        (root / 'template-samples.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (root / 'fonts.json').write_text(json.dumps(font_config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if sum(path.stat().st_size for path in root.rglob('*') if path.is_file()) > 100 * 1024 * 1024:
            raise ValueError('template starter project exceeds 100 MiB')
        root.rename(destination)
    return dict(status='template_samples_created', manifest=str(destination / 'deck.pptd'),
                report=str(destination / 'template-samples.json'), pages=len(samples), issues=len(issues), fontSubstitutions=substitutions)
