"""Native exporter acceptance and failure isolation; see NATIVE_NOTICE.md."""
import importlib.util
from copy import deepcopy
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'skills/pptd-deck-skill/scripts'
sys.path.insert(0, str(SCRIPTS / 'local-export'))
sys.path.insert(0, str(ROOT / 'tools'))
from native_common import NS, NativeExportError
from native_math import parse as parse_math
from native_animation import schedule
from native_table import grid, cell_style, ratios
from native_preview import preview
from native_text import RichText
from pptx_semantics import snapshot, differences, validate_package

SPEC = importlib.util.spec_from_file_location('native_test_cli', SCRIPTS / 'export_pptx.py')
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class NativeExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-export-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = Path(__file__).parent / 'fixtures/native'

    def export(self, project=None, transition='fade'):
        output = self.root / 'output.pptx'
        result = CLI.export_pptx(project or self.fixture, output, transition, force=True, backend='native')
        return output, result

    def project(self, page, manifest=None):
        root = self.root / 'project'
        root.mkdir(exist_ok=True)
        deck = dict(version='v2', size=[960, 540], pages=['one.page'])
        deck.update(manifest or {})
        (root / 'deck.pptd').write_text(CLI.yaml.safe_dump(deck), encoding='utf-8')
        (root / 'one.page').write_text(CLI.yaml.safe_dump(page, allow_unicode=True), encoding='utf-8')
        return root

    @staticmethod
    def text(value, **content):
        return dict(elementId='text', elementType='text', bounds=[20, 30, 800, 200], content=dict(text=value, **content))

    def test_native_never_loads_legacy_or_starts_a_process(self):
        import subprocess
        with patch.object(subprocess, 'run', side_effect=AssertionError('subprocess')):
            output, result = self.export()
        self.assertEqual(result['exporter'], 'native-python-v1')
        self.assertEqual(result['slides'], 2)
        with zipfile.ZipFile(output) as archive:
            validate_package(archive)
            self.assertFalse(any(n.endswith('.wasm') or '/fonts/' in n for n in archive.namelist()))

    def test_reproducible_bytes_and_media_deduplication(self):
        output, _ = self.export()
        first = output.read_bytes()
        self.export()
        self.assertEqual(first, output.read_bytes())
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.startswith('ppt/media/')]), 1)
            media = next(n for n in archive.namelist() if n.startswith('ppt/media/'))
            self.assertEqual(archive.read(media), (self.fixture / 'media/blocks.png').read_bytes())
            self.assertIn(b'<Types xmlns=', archive.read('[Content_Types].xml'))


    def test_geometry_crop_and_font_names_are_explicit(self):
        output, _ = self.export()
        model = snapshot(output)
        self.assertEqual(model['size']['cx'], '12192000')
        self.assertEqual(model['size']['cy'], '6858000')
        self.assertEqual(model['slides'][1]['shapes'][1]['image']['crop']['l'], '25000')
        self.assertEqual(model['slides'][1]['shapes'][2]['image']['crop']['t'], '-50000')
        with zipfile.ZipFile(output) as archive:
            xml = archive.read('ppt/slides/slide1.xml')
            self.assertIn(b'typeface="Arial"', xml)
            self.assertIn(b'typeface="Noto Sans SC"', xml)

    def test_formula_structure_and_plain_fallback_are_preserved(self):
        formula = r'\(\frac{x_1^2+\alpha}{\sqrt{y}} = \int_0^1 x^2\mathrm{d}x\)'
        output, _ = self.export(self.project({'elements': [self.text(formula)]}))
        with zipfile.ZipFile(output) as archive:
            validate_package(archive)
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            for tag in ['m:f', 'm:rad', 'm:sSubSup', 'm:nary']:
                self.assertIsNotNone(root.find('.//' + tag, NS), tag)
            self.assertEqual(root.find('.//mc:Fallback//a:t', NS).text, formula)
            self.assertEqual(root.find('.//mc:Choice', NS).get('Requires'), 'a14')
            differential = next(r for r in root.findall('.//m:r', NS) if r.findtext('m:t', namespaces=NS) == 'd')
            self.assertEqual(differential.find('m:rPr/m:sty', NS).get('{' + NS['m'] + '}val'), 'p')

    def test_math_parser_rejects_unknown_commands_and_malformed_input(self):
        for source in [r'\input{secret}', r'\foo', r'\frac{a}', 'x^^2', 'x^{2', 'x}', '$x$', '{' * 70 + 'x' + '}' * 70]:
            with self.subTest(source=source):
                with self.assertRaises(NativeExportError):
                    parse_math(source)

    def test_math_recursion_is_bounded_without_braces(self):
        for source in [r'\frac' * 500 + 'x' * 501, r'\sum' * 500 + 'x']:
            with self.assertRaisesRegex(NativeExportError, 'nesting'):
                parse_math(source)

    def test_semantic_comparison_detects_formula_and_table_content_changes(self):
        project = Path(__file__).parent / 'fixtures/native-advanced'
        output, _ = self.export(project)
        baseline = snapshot(output)
        self.assertEqual(baseline['slides'][0]['shapes'][1]['kind'], 'sp')
        self.assertIn('math', baseline['slides'][0]['shapes'][1]['paragraphs'][0]['runs'][1])
        self.assertIn('graphicData', baseline['slides'][1]['shapes'][1])
        with zipfile.ZipFile(output) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts['ppt/slides/slide1.xml'] = parts['ppt/slides/slide1.xml'].replace(b'<m:t>a</m:t>', b'<m:t>z</m:t>')
        parts['ppt/slides/slide2.xml'] = parts['ppt/slides/slide2.xml'].replace(b'>C3<', b'>changed<')
        changed = self.root / 'changed.pptx'
        with zipfile.ZipFile(changed, 'w') as archive:
            for name, value in parts.items():
                archive.writestr(name, value)
        diff = differences(baseline, snapshot(changed))
        self.assertTrue(any('.runs' in d['path'] for d in diff))
        self.assertTrue(any('.graphicData' in d['path'] for d in diff))

    def test_merged_table_grid_and_style_precedence(self):
        rows = [[{'text': 'merged', 'rowSpan': 2, 'colSpan': 2}, {'text': 'C1'}],
                [{'text': 'C2'}], [{'text': 'A3'}, {'text': 'B3'}, {'text': 'C3'}]]
        table = dict(elementId='t', elementType='table', bounds=[50, 100, 600, 240],
                     columnWidths=[.3, .3, .4], rowHeights=[.3, .3, .4], rows=rows,
                     style={'cellStyle': {'fontFamily': 'Arial', 'fontSize': 20},
                            'firstRowStyle': {'color': '#FF0000'}, 'firstColumnStyle': {'color': '#0000FF'}})
        output, _ = self.export(self.project({'elements': [table]}))
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            cells = root.findall('.//a:tc', NS)
            self.assertEqual(len(cells), 9)
            self.assertEqual(cells[0].get('rowSpan'), '2')
            self.assertEqual(cells[0].get('gridSpan'), '2')
            self.assertEqual(cells[4].attrib, {'hMerge': '1', 'vMerge': '1'})
            self.assertEqual(cells[0].find('.//a:srgbClr', NS).get('val'), 'FF0000')
            self.assertEqual(sum(int(c.get('w')) for c in root.findall('.//a:gridCol', NS)), 600 * 12700)
        with self.assertRaises(NativeExportError):
            grid([[{'rowSpan': 2, 'colSpan': 3}]], 1, 2)

    def test_table_null_border_overrides_style(self):
        style = cell_style({}, {'cellStyle': {'border': {'width': 1}}}, {'border': None}, 0, 0, 1, 1, {})
        self.assertIsNone(style['border'])

    def test_mixed_shorthand_cells_and_nonunit_ratios_match_preview_and_export(self):
        rows = [[{'text': 'Merged', 'rowSpan': 2}, 'Top'], ['Bottom']]
        table = dict(elementId='mixed', elementType='table', bounds=[0, 0, 600, 200],
                     columnWidths=[.49, .49], rowHeights=[.51, .51], rows=rows,
                     style={'cellStyle': {'fontSize': 13}, 'firstRowStyle': {'bold': True}})
        before = deepcopy(table)
        data = preview({'elements': [table]}, {})['mixed']
        self.assertEqual([c['text'] for c in data['cells']], ['Merged', 'Top', 'Bottom'])
        self.assertEqual(data['cells'][2]['sourceIndex'], 0)
        self.assertTrue(data['cells'][1]['style']['bold'])
        self.assertEqual(sum(data['widths']), 1)
        self.assertEqual(sum(data['heights']), 1)
        output, _ = self.export(self.project({'elements': [table]}))
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            self.assertEqual(root.find('.//a:tc', NS).get('rowSpan'), '2')
            self.assertEqual([n.text for n in root.findall('.//a:tbl//a:t', NS)], ['Merged', 'Top', 'Bottom'])
            self.assertEqual(sum(int(c.get('w')) for c in root.findall('.//a:gridCol', NS)), 600 * 12700)
            self.assertEqual(sum(int(r.get('h')) for r in root.findall('.//a:tr', NS)), 200 * 12700)
        self.assertEqual(table, before)
        for values in ([], [0, 1], [-.1, 1], [True], [1.1], [float('nan')]):
            with self.subTest(values=values), self.assertRaises(NativeExportError):
                ratios(values, 'rowHeights')
        for cell in (42, None, True, []):
            with self.subTest(cell=cell), self.assertRaises(NativeExportError):
                grid([[cell]], 1, 1)

    def test_multiline_html_ignores_block_whitespace_and_exports_theme_run_colors(self):
        text = '\n<p><strong style="color:$accent;font-weight:normal">A</strong></p>\n<p><span style="color:$muted;font-size:12px">Note</span></p>\n'
        parsed = RichText(text, {})
        self.assertEqual(len(parsed.paragraphs), 2)
        self.assertEqual(parsed.paragraphs[1][1][0][1]['color'], '$muted')
        self.assertTrue(parsed.paragraphs[0][1][0][1]['bold'])
        output, _ = self.export(self.project({'elements': [self.text(text)]},
            {'theme': {'colors': {'accent': '#116655', 'muted': '#8899AA'}}}))
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            runs = root.findall('.//p:sp/p:txBody/a:p/a:r', NS)
            self.assertEqual([r.findtext('a:t', namespaces=NS) for r in runs], ['A', 'Note'])
            self.assertEqual([r.find('a:rPr/a:solidFill/a:srgbClr', NS).get('val') for r in runs], ['116655', '8899AA'])

    def test_shadows_and_outset_crop_follow_documented_fit_order(self):
        output, _ = self.export(Path(__file__).parent / 'fixtures/native-effects')
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            shade = root.find('.//p:spPr/a:effectLst/a:outerShdw', NS)
            self.assertEqual(shade.get('dist'), '127000')  # hypot(-6, 8) points
            self.assertEqual(shade.get('blurRad'), '76200')
            self.assertEqual(shade.get('dir'), '7612194')
            self.assertEqual(shade.find('a:srgbClr/a:alpha', NS).get('val'), '50196')
            self.assertIsNotNone(root.find('.//a:rPr/a:effectLst/a:outerShdw', NS))
        shapes = snapshot(output)['slides'][0]['shapes']
        fill_crop = shapes[2]['image']['crop']
        self.assertEqual(fill_crop, dict(l='-25000', t='-50000', r='12500', b='10000'))
        for shape in shapes[3:]:
            crop = {key: int(value) / 100000 for key, value in shape['image']['crop'].items()}
            self.assertAlmostEqual(120 * (1 - crop['l'] - crop['r']) /
                                   (60 * (1 - crop['t'] - crop['b'])), 160 / 240, places=4)
        self.assertNotEqual(shapes[3]['image']['crop'], shapes[4]['image']['crop'])


    def test_image_fills_have_slide_relationships_and_merged_cell_dimensions(self):
        image = dict(type='image', src='blocks.png', fit={'mode': 'contain'}, opacity=.6)
        table = dict(elementType='table', elementId='merged-image', bounds=[50, 50, 600, 300],
                     columnWidths=[.2, .2, .6], rowHeights=[.3, .7],
                     rows=[[dict(text='merged', rowSpan=2, colSpan=2, fill=image), {'text': 'a'}],
                           [{'text': 'b'}]])
        project = self.project({'background': image, 'elements': [table]})
        shutil.copyfile(self.fixture / 'media/blocks.png', project / 'blocks.png')
        output, _ = self.export(project)
        with zipfile.ZipFile(output) as archive:
            validate_package(archive)
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            crop = root.find('.//a:tcPr/a:blipFill/a:srcRect', NS)
            self.assertEqual(crop.get('t'), '-75000')  # 240 x 300 merged bounds, 120 x 60 source
            self.assertEqual(crop.get('b'), '-75000')
            self.assertEqual(len(root.findall('.//a:blip', NS)), 2)
            self.assertEqual(len([n for n in archive.namelist() if n.startswith('ppt/media/')]), 1)


    def test_invalid_geometry_fails_cleanly_before_publishing(self):
        output = self.root / 'output.pptx'
        output.write_bytes(b'previous output')
        for size in (None, [1], [960, float('nan')], [10 ** 400, 540]):
            with self.subTest(size=size):
                project = self.project({'elements': []}, {'size': size})
                with self.assertRaises(CLI.ExportError):
                    self.export(project)
                self.assertEqual(output.read_bytes(), b'previous output')
        for element in [dict(self.text('large'), bounds=[1e308, 0, 1, 1]),
                        self.text('large', lineHeight=1e308), self.text('large', marginTop=1e308)]:
            with self.assertRaises(CLI.ExportError):
                self.export(self.project({'elements': [element]}))
            self.assertEqual(output.read_bytes(), b'previous output')

    def test_animation_groups_and_order(self):
        animations = [dict(elementId='text', effect='fade-in', durationMs=800),
                      dict(elementId='text', effect='fade-out', trigger='afterPrevious', delayMs=400),
                      dict(elementId='text', effect='appear', trigger='onClick')]
        groups = schedule(animations, {'text': 2})
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][1][1].start, 1200)
        output, _ = self.export(self.project({'elements': [self.text('Animated')], 'animations': animations}))
        with zipfile.ZipFile(output) as archive:
            root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
            children = [e.tag.rsplit('}', 1)[-1] for e in root]
            self.assertLess(children.index('transition'), children.index('timing'))
            ids = [e.get('id') for e in root.findall('.//p:cTn', NS)]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual({e.get('spid') for e in root.findall('.//p:spTgt', NS)}, {'2'})

    def test_none_transition_has_no_transition_element(self):
        output, result = self.export(transition='none')
        self.assertEqual(result['fadeTransitions'], 0)
        self.assertTrue(all(s['transition'] is None for s in snapshot(output)['slides']))

    def test_unsupported_features_do_not_replace_previous_output(self):
        output = self.root / 'output.pptx'
        output.write_bytes(b'previous output')
        cases = [self.text(r'\(\unknown{x}\)'), self.text('<img src="x">'),
                 self.text('test', gradient={'type': 'gradient'}),
                 dict(elementId='chart', elementType='chart', bounds=[0, 0, 100, 100]),
                 dict(elementId='img', elementType='image', bounds=[0, 0, 100, 100], src='../secret.png')]
        for element in cases:
            with self.subTest(element=element):
                project = self.project({'elements': [element]})
                with self.assertRaises(CLI.ExportError):
                    self.export(project)
                self.assertEqual(output.read_bytes(), b'previous output')

    def test_invalid_coordinates_styles_and_duplicate_ids_fail(self):
        for page in [
            {'elements': [dict(self.text('x'), bounds=[0, 0, float('nan'), 10])]},
            {'elements': [self.text('x'), self.text('duplicate')]},
            {'elements': [self.text('x', color='$cycle')]},
            {'elements': [self.text('x')], 'animations': [{'elementId': 'missing', 'effect': 'appear'}]},
        ]:
            with self.subTest(page=page):
                with self.assertRaises(CLI.ExportError):
                    self.export(self.project(page, {'theme': {'colors': {'cycle': '$cycle'}}}))

    def test_page_symlink_cannot_escape_project(self):
        secret = self.root / 'secret.page'
        secret.write_text('elements: []')
        project = self.project({'elements': []})
        (project / 'one.page').unlink()
        (project / 'one.page').symlink_to(secret)
        with self.assertRaisesRegex(CLI.ExportError, 'outside project'):
            self.export(project)

    def test_backend_option_conflicts_fail_without_fallback(self):
        for kwargs in [dict(prefer_local=False), dict(keep_download=True)]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(CLI.ExportError, 'cannot be combined'):
                    CLI.export_pptx(self.fixture, self.root / 'out.pptx', 'fade', backend='native', **kwargs)


if __name__ == '__main__':
    unittest.main()
