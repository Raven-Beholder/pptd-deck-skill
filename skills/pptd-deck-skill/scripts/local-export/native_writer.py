"""Auditable, dependency-free OOXML writer for the native-v1 PPTD subset.

Input YAML parsing is handled by the existing CLI. There is no WASM, network,
signature, browser, bundled template or third-party exporter in this module.
See NATIVE_NOTICE.md for provenance and unresolved licensing review.
"""
from native_common import (NS, NativeExportError, boolean, choice, color, emu, fields,
                           node, number, project_path, string, vector)
from native_media import Media
from native_fill import fill, image_fill
from native_package import Package
from native_text import text_body
from native_table import write_table
from native_animation import timing
from native_effects import shadow
from native_chart import write_chart
from native_project_fonts import project_fonts, embed_project_fonts, declared_font_defaults

PRESENTATION_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.'
SHAPES = ('rect', 'roundRect', 'ellipse', 'triangle', 'diamond', 'parallelogram',
          'trapezoid', 'pentagon', 'hexagon', 'octagon', 'chevron', 'homePlate',
          'rightArrow', 'leftArrow', 'upArrow', 'downArrow', 'star5', 'donut',
          'round1Rect', 'round2SameRect', 'round2DiagRect', 'snip1Rect', 'snip2SameRect', 'snip2DiagRect', 'snipRoundRect', 'rtTriangle', 'heptagon', 'decagon', 'dodecagon', 'plus', 'leftRightArrow', 'upDownArrow', 'star4', 'star6', 'star8', 'heart')
BASE_FIELDS = 'elementId elementType bounds rotation opacity flip'


def border(parent, spec, theme, opacity=1, arrows=None):
    if spec is None:
        node('a:noFill', node('a:ln', parent))
        return
    fields(spec, 'style width color', 'border')
    line = node('a:ln', parent, w=emu(number(spec.get('width', 1), 'border.width', 0)))
    color(node('a:solidFill', line), spec.get('color', '#000000'), theme, opacity)
    dash = choice(spec.get('style', 'solid'), {'solid': 'solid', 'dash': 'dash', 'dot': 'sysDot'}, 'border.style')
    node('a:prstDash', line, val=dash)
    if arrows is not None:
        if not isinstance(arrows, list) or len(arrows) != 2:
            raise NativeExportError('line.arrow: expected [start, end]')
        for tag, arrow in zip(('a:headEnd', 'a:tailEnd'), arrows):
            kind = choice(arrow, {None: 'none', 'arrow': 'triangle', 'stealth': 'stealth', 'diamond': 'diamond', 'oval': 'oval'}, 'arrow')
            node(tag, line, type=kind, w='med', len='med')


def transform(parent, bounds, element):
    rotation = number(element.get('rotation', 0), 'rotation')
    flip = element.get('flip', [False, False])
    if not isinstance(flip, list) or len(flip) != 2:
        raise NativeExportError('flip: expected two booleans')
    attrs = {}
    if rotation:
        attrs['rot'] = round(rotation % 360 * 60000)
    for key, value in zip(('flipH', 'flipV'), flip):
        if boolean(value, 'flip'):
            attrs[key] = '1'
    xfrm = node('a:xfrm', parent, **attrs)
    x, y, width, height = bounds
    node('a:off', xfrm, x=emu(x), y=emu(y))
    node('a:ext', xfrm, cx=emu(width), cy=emu(height))


def group(parent):
    tree = node('p:spTree', parent)
    nv = node('p:nvGrpSpPr', tree)
    node('p:cNvPr', nv, id=1, name='')
    node('p:cNvGrpSpPr', nv)
    node('p:nvPr', nv)
    xfrm = node('a:xfrm', node('p:grpSpPr', tree))
    for tag, attrs in [('off', dict(x=0, y=0)), ('ext', dict(cx=0, cy=0)),
                       ('chOff', dict(x=0, y=0)), ('chExt', dict(cx=0, cy=0))]:
        node('a:' + tag, xfrm, **attrs)
    return tree


def geometry(parent, name):
    choice(name, SHAPES, 'shapeName')
    node('a:avLst', node('a:prstGeom', parent, prst=name))


class Writer:
    def __init__(self, deck, root, transition, *, embed_fonts=False):
        self.deck = deck
        self.size = vector(deck.get('size'), 2, 'size', 1)
        if max(self.size) > 10000:
            raise NativeExportError('slide size exceeds native-v1 limit of 10000 points')
        self.theme = deck.get('theme', {})
        fields(self.theme, 'colors textStyles tableStyles', 'theme')
        for key in self.theme:
            if not isinstance(self.theme[key], dict):
                raise NativeExportError(f'theme.{key}: expected mapping')
        self.package = Package()
        self.media = Media(root, self.package)
        self.transition = choice(transition, ('fade', 'none'), 'transition')
        self.fonts = project_fonts(root, deck.get('customFonts'), allow_missing=True)
        self.package.default_font, self.package.math_font = declared_font_defaults(deck.get('customFonts'), self.fonts)
        self.package.has_project_text_font = any(entry.get('role', 'text') == 'text' for entry in deck.get('customFonts', []))
        self.embed_fonts = boolean(embed_fonts, 'embed_fonts')

    def draw_fill(self, parent, value, owner, bounds, opacity=1):
        fill(parent, value, self.theme, opacity, media=self.media, owner=owner, bounds=bounds)

    def draw_border(self, parent, value):
        border(parent, value, self.theme)

    def element(self, tree, element, index, owner):
        if not isinstance(element, dict):
            raise NativeExportError('element: expected mapping')
        kind = choice(element.get('elementType'), ('text', 'shape', 'image', 'line', 'table', 'chart'), 'elementType')
        bounds = vector(element.get('bounds'), 4, 'bounds')
        if bounds[2] <= 0 or bounds[3] <= 0:
            raise NativeExportError('native-v1 bounds width and height must be positive')
        if kind == 'chart':
            write_chart(self, tree, element, index, owner, bounds)
            return
        if kind == 'table':
            frame = write_table(self, tree, element, index, owner, bounds)
            if frame.find('.//a14:m', NS) is not None:
                tree.remove(frame)
                alternate = node('mc:AlternateContent', tree)
                node('mc:Choice', alternate, Requires='a14').append(frame)
                write_table(self, node('mc:Fallback', alternate), element, index, owner, bounds, math_mode=False)
            return
        extra = {'text': 'content', 'shape': 'shapeName fill border shadow',
                 'image': 'src fit crop border shadow', 'line': 'viewBox points curve border arrow shadow'}[kind]
        fields(element, BASE_FIELDS + ' ' + extra, kind)
        opacity = number(element.get('opacity', 1), 'opacity', 0, 1)
        image = kind == 'image'
        shape = node('p:pic' if image else 'p:sp', tree)
        nv = node('p:nvPicPr' if image else 'p:nvSpPr', shape)
        node('p:cNvPr', nv, id=index, name=string(element.get('elementId'), 'elementId'))
        node('p:cNvPicPr' if image else 'p:cNvSpPr', nv, **({'txBox': '1'} if kind == 'text' else {}))
        node('p:nvPr', nv)
        if image:
            image_fill(shape, 'p:blipFill', element, self.media, owner, bounds, opacity)
        props = node('p:spPr', shape)
        transform(props, bounds, element)
        if kind == 'line':
            self.line_geometry(props, element)
        else:
            geometry(props, element.get('shapeName', 'rect'))
        if not image:
            self.draw_fill(props, element.get('fill'), owner, bounds, opacity)
        border(props, element.get('border'), self.theme, opacity, element.get('arrow'))
        shadow(props, element.get('shadow'), self.theme)
        if kind == 'text':
            text_body(shape, element.get('content'), self.theme, self.package, owner, opacity)
            if shape.find('.//a14:m', NS) is not None:
                from copy import deepcopy
                fallback = deepcopy(shape)
                fallback.remove(fallback.find('p:txBody', NS))
                text_body(fallback, element['content'], self.theme, self.package, owner, opacity, math_mode=False)
                tree.remove(shape)
                alternate = node('mc:AlternateContent', tree)
                node('mc:Choice', alternate, Requires='a14').append(shape)
                node('mc:Fallback', alternate).append(fallback)

    def line_geometry(self, parent, element):
        choice(element.get('curve', 'round'), ('sharp', 'round'), 'line.curve')
        size = vector(element.get('viewBox'), 2, 'line.viewBox', 0.0001)
        points = string(element.get('points'), 'line.points').split()
        if len(points) != 2:
            raise NativeExportError('native-v1 supports straight two-point lines only')
        try:
            points = [vector([float(v) for v in p.split(',')], 2, 'line point') for p in points]
        except ValueError as exc:
            raise NativeExportError('invalid line points') from exc
        for x, y in points:
            if not 0 <= x <= size[0] or not 0 <= y <= size[1]:
                raise NativeExportError('line points outside viewBox')
        geom = node('a:custGeom', parent)
        for tag in ('avLst', 'gdLst', 'ahLst', 'cxnLst'):
            node('a:' + tag, geom)
        node('a:rect', geom, l=0, t=0, r='r', b='b')
        path = node('a:path', node('a:pathLst', geom), w=emu(size[0]), h=emu(size[1]), fill='none')
        for tag, (x, y) in zip(('moveTo', 'lnTo'), points):
            node('a:pt', node('a:' + tag, path), x=emu(x), y=emu(y))

    def slides(self):
        for index, page in enumerate(self.deck['pages'], 1):
            fields(page, 'pageType background elements notes animations', f'page {index}')
            owner = f'ppt/slides/slide{index}.xml'
            slide = node('p:sld')
            common = node('p:cSld', slide)
            bg = node('p:bgPr', node('p:bg', common))
            self.draw_fill(bg, page.get('background', {'type': 'solid', 'color': '#FFFFFF'}),
                           owner, [0, 0, *self.size])
            node('a:effectLst', bg)
            tree = group(common)
            ids = set()
            elements = page.get('elements')
            if not isinstance(elements, list):
                raise NativeExportError(f'page {index}: elements must be an array')
            for element_index, element in enumerate(elements, 2):
                try:
                    if not isinstance(element, dict):
                        raise NativeExportError('element must be a mapping')
                    identifier = string(element.get('elementId'), 'elementId')
                    if not identifier or identifier in ids:
                        raise NativeExportError('empty or duplicate elementId')
                    ids.add(identifier)
                    self.element(tree, element, element_index, owner)
                except NativeExportError as exc:
                    raise NativeExportError(f'page {index}, element {element_index - 1}: {exc}') from exc
            node('a:masterClrMapping', node('p:clrMapOvr', slide))
            if self.transition == 'fade':
                node('p:fade', node('p:transition', slide, spd='fast', advClick='1'))
            timing(slide, page.get('animations', []),
                   {element['elementId']: i for i, element in enumerate(elements, 2)})
            self.package.relate(owner, '../slideLayouts/slideLayout1.xml', 'slideLayout')
            if page.get('notes') is not None:
                self.notes(index, string(page['notes'], 'notes'))
            self.package.add(owner, slide, PRESENTATION_TYPE + 'slide+xml')

    def notes(self, index, text):
        notes = node('p:notes')
        tree = group(node('p:cSld', notes))
        shape = node('p:sp', tree)
        nv = node('p:nvSpPr', shape)
        node('p:cNvPr', nv, id=2, name='Notes')
        node('p:cNvSpPr', nv)
        node('p:ph', node('p:nvPr', nv), type='body', idx=1)
        node('p:spPr', shape)
        owner = f'ppt/notesSlides/notesSlide{index}.xml'
        body = node('p:txBody', shape)
        node('a:bodyPr', body)
        node('a:lstStyle', body)
        for line in text.split('\n'):
            node('a:t', node('a:r', node('a:p', body)), text=line)
        node('a:masterClrMapping', node('p:clrMapOvr', notes))
        self.package.add(owner, notes, PRESENTATION_TYPE + 'notesSlide+xml')
        self.package.relate(owner, '../notesMasters/notesMaster1.xml', 'notesMaster')
        self.package.relate(owner, f'../slides/slide{index}.xml', 'slide')
        self.package.relate(f'ppt/slides/slide{index}.xml', f'../notesSlides/notesSlide{index}.xml', 'notesSlide')

    def scaffold(self):
        package = self.package
        presentation = node('p:presentation')
        owner = 'ppt/presentation.xml'
        master_rid = package.relate(owner, 'slideMasters/slideMaster1.xml', 'slideMaster')
        node('p:sldMasterId', node('p:sldMasterIdLst', presentation), id=2147483648, **{'r:id': master_rid})
        if any(page.get('notes') is not None for page in self.deck['pages']):
            rid = package.relate(owner, 'notesMasters/notesMaster1.xml', 'notesMaster')
            node('p:notesMasterId', node('p:notesMasterIdLst', presentation), **{'r:id': rid})
        slides = node('p:sldIdLst', presentation)
        for index in range(1, len(self.deck['pages']) + 1):
            rid = package.relate(owner, f'slides/slide{index}.xml', 'slide')
            node('p:sldId', slides, id=255 + index, **{'r:id': rid})
        width, height = self.size
        node('p:sldSz', presentation, cx=emu(width), cy=emu(height), type='custom')
        node('p:notesSz', presentation, cx=emu(540), cy=emu(720))
        if self.embed_fonts:
            embed_project_fonts(package, presentation, self.fonts)
        package.add(owner, presentation, PRESENTATION_TYPE + 'presentation.main+xml')
        package.relate('', owner, 'officeDocument')
        core = node('cp:coreProperties')
        node('dc:title', core, text=string(self.deck.get('title', ''), 'title'))
        node('dc:creator', core, text='Native PPTD exporter')
        package.add('docProps/core.xml', core, 'application/vnd.openxmlformats-package.core-properties+xml')
        package.relate('', 'docProps/core.xml', 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties')
        master = node('p:sldMaster')
        group(node('p:cSld', master))
        self.color_map(master)
        rid = package.relate('ppt/slideMasters/slideMaster1.xml', '../slideLayouts/slideLayout1.xml', 'slideLayout')
        node('p:sldLayoutId', node('p:sldLayoutIdLst', master), id=2147483649, **{'r:id': rid})
        node('p:txStyles', master)
        package.add('ppt/slideMasters/slideMaster1.xml', master, PRESENTATION_TYPE + 'slideMaster+xml')
        layout = node('p:sldLayout', type='blank', preserve='1')
        group(node('p:cSld', layout, name='Blank'))
        node('a:masterClrMapping', node('p:clrMapOvr', layout))
        package.add('ppt/slideLayouts/slideLayout1.xml', layout, PRESENTATION_TYPE + 'slideLayout+xml')
        package.relate('ppt/slideLayouts/slideLayout1.xml', '../slideMasters/slideMaster1.xml', 'slideMaster')
        package.relate('ppt/slideMasters/slideMaster1.xml', '../theme/theme1.xml', 'theme')
        if any(page.get('notes') is not None for page in self.deck['pages']):
            notes = node('p:notesMaster')
            group(node('p:cSld', notes))
            self.color_map(notes)
            node('p:notesStyle', notes)
            package.add('ppt/notesMasters/notesMaster1.xml', notes, PRESENTATION_TYPE + 'notesMaster+xml')
            # PowerPoint expects a separate theme part for the notes master.
            # Sharing the slide master's part causes a repair on import.
            package.relate('ppt/notesMasters/notesMaster1.xml', '../theme/notesTheme.xml', 'theme')
            self.theme_part('ppt/theme/notesTheme.xml')
        self.theme_part()

    @staticmethod
    def color_map(parent):
        node('p:clrMap', parent, bg1='lt1', tx1='dk1', bg2='lt2', tx2='dk2',
             **{key: key for key in ['accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink']})

    def theme_part(self, owner='ppt/theme/theme1.xml'):
        theme = node('a:theme', name='Native PPTD')
        elements = node('a:themeElements', theme)
        colors = node('a:clrScheme', elements, name='Native')
        for key, value in zip(('dk1', 'lt1', 'dk2', 'lt2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink'),
                              ('000000', 'FFFFFF', '222222', 'EEEEEE', '2563EB', 'F59E0B', '16A34A', '9333EA', 'DC2626', '0891B2', '0563C1', '954F72')):
            node('a:srgbClr', node('a:' + key, colors), val=value)
        fonts = node('a:fontScheme', elements, name='Native')
        for tag in ('majorFont', 'minorFont'):
            item = node('a:' + tag, fonts)
            for script in ('latin', 'ea', 'cs'):
                node('a:' + script, item, typeface=self.package.default_font)
        formats = node('a:fmtScheme', elements, name='Native')
        for tag in ('fillStyleLst', 'lnStyleLst', 'effectStyleLst', 'bgFillStyleLst'):
            styles = node('a:' + tag, formats)
            for _ in range(3):
                if tag == 'effectStyleLst':
                    node('a:effectLst', node('a:effectStyle', styles))
                else:
                    target = node('a:ln', styles, w=12700) if tag == 'lnStyleLst' else styles
                    node('a:schemeClr', node('a:solidFill', target), val='phClr')
        self.package.add(owner, theme, 'application/vnd.openxmlformats-officedocument.theme+xml')


def export_native(manifest, destination, transition, parse_yaml, *, embed_fonts=False):
    root = manifest.parent.resolve()
    deck = parse_yaml(manifest.read_text(encoding='utf-8'))
    fields(deck, 'version title size theme pages customFonts', 'presentation')
    if deck.get('version') != 'v2':
        raise NativeExportError('only PPTD v2 is supported')
    paths = deck.get('pages')
    if not isinstance(paths, list) or not paths:
        raise NativeExportError('pages must be a nonempty array')
    deck = dict(deck, pages=[parse_yaml(project_path(root, p).read_text(encoding='utf-8')) for p in paths])
    writer = Writer(deck, root, transition, embed_fonts=embed_fonts)
    writer.slides()
    writer.scaffold()
    # The complete package is constructed before opening the staged destination.
    writer.package.write(destination)
    return len(deck['pages'])
