"""Chart/workbook agreement, Office interoperability fixes and fail isolation."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'skills/pptd-deck-skill/scripts/local-export'))
sys.path.insert(0, str(ROOT / 'tools'))
from native_chart_model import model
from native_cli import export
from native_common import NS, NativeExportError
from native_preview import preview
from pptx_semantics import snapshot, relationships, workbook_snapshot

FIXTURE = Path(__file__).parent / 'fixtures/native-charts'


class NativeChartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-chart-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chart = yaml.safe_load((FIXTURE / 'pages/01.page').read_text())['elements'][1]

    def output(self, chart=None):
        output = self.root / 'output.pptx'
        if chart is None:
            export(FIXTURE, output, force=True)
        else:
            (self.root / 'one.page').write_text(yaml.safe_dump(dict(elements=[chart])))
            (self.root / 'deck.pptd').write_text('version: v2\nsize: [960,540]\npages: [one.page]\n')
            export(self.root, output, force=True)
        return output

    def test_all_chart_caches_match_editable_workbooks(self):
        path = self.output()
        data = snapshot(path)
        charts = [s['chart'] for page in data['slides'] for s in page['shapes'] if 'chart' in s]
        self.assertEqual(len(charts), 9)
        self.assertEqual(charts[0]['workbook'][0]['cells']['B3'], 22)
        self.assertEqual(charts[1]['workbook'][0]['cells'].get('C3'), None)
        self.assertEqual(charts[2]['workbook'][0]['cells']['B2'], '研发 Engineering')
        self.assertEqual(path.read_bytes(), self.output().read_bytes())

    def test_horizontal_axes_are_referenced_category_before_value(self):
        with ZipFile(self.output()) as archive:
            tree = ET.fromstring(archive.read('ppt/charts/chart3.xml'))
            ids = [n.get('val') for n in tree.findall('.//c:barChart/c:axId', NS)]
            self.assertEqual(ids, ['2', '1'])
            self.assertEqual(tree.find('.//c:catAx/c:axId', NS).get('val'), ids[0])
            self.assertEqual(tree.find('.//c:valAx/c:axId', NS).get('val'), ids[1])

    def test_notes_master_has_its_own_theme_part(self):
        with ZipFile(self.output()) as archive:
            a = next(r['target'] for r in relationships(archive, 'ppt/slideMasters/slideMaster1.xml').values() if r['type'] == 'theme')
            b = next(r['target'] for r in relationships(archive, 'ppt/notesMasters/notesMaster1.xml').values() if r['type'] == 'theme')
            self.assertNotEqual(a, b)
            self.assertEqual(archive.read(a), archive.read(b))

    def test_normalization_does_not_mutate_input_and_keeps_literal_text(self):
        chart = deepcopy(self.chart)
        chart['data']['rows'][0][0] = '=SUM(B2:B4)'
        before = deepcopy(chart)
        normalized = model(chart, {})
        self.assertEqual(chart, before)
        self.assertEqual(normalized['series'][1]['values'][0], 9)
        with ZipFile(self.output(chart)) as archive:
            with ZipFile(BytesIO(archive.read('ppt/embeddings/chart1.xlsx'))) as workbook:
                sheet = ET.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
                self.assertIsNone(sheet.find('.//s:f', NS))
                self.assertEqual(sheet.find('.//s:c[@r="A2"]/s:is/s:t', NS).text, '=SUM(B2:B4)')

    def test_numeric_categories_keep_precision_in_cache_and_workbook(self):
        chart = deepcopy(self.chart)
        chart['xAxis'] = dict(type='category')
        chart['data']['rows'][0][0] = 1.234567891234567
        self.assertTrue(snapshot(self.output(chart)))

    def test_literal_escape_sequences_and_whitespace_survive_workbook_and_chart_cache(self):
        chart = deepcopy(self.chart)
        value = '  literal _x000A_ / _x005f_ / CR\rLF\n  '
        chart['data']['rows'][0][0] = value
        chart['series'][0]['name'] = '_x0020_ literal name'
        result = snapshot(self.output(chart))['slides'][0]['shapes'][0]['chart']
        self.assertEqual(result['workbook'][0]['cells']['A2'], value)
        series = result['features']['groups'][0]['series'][0]
        self.assertEqual(series['categories'][0], value)
        self.assertEqual(series['name'], '_x0020_ literal name')

    def test_mismatched_cache_and_workbook_is_detected(self):
        path = self.output()
        with ZipFile(path) as archive:
            parts = {n: archive.read(n) for n in archive.namelist()}
        parts['ppt/charts/chart1.xml'] = parts['ppt/charts/chart1.xml'].replace(b'>14<', b'>140<', 1)
        with ZipFile(path, 'w') as archive:
            for n, data in parts.items(): archive.writestr(n, data)
        with self.assertRaisesRegex(ValueError, 'cache differs'):
            snapshot(path)

    def test_unsupported_chart_preserves_previous_output(self):
        self.output().write_bytes(b'previous output')
        chart = deepcopy(self.chart); chart['series'][0]['yAxisIndex'] = 1
        with self.assertRaisesRegex(NativeExportError, 'secondary axes'):
            self.output(chart)
        self.assertEqual((self.root / 'output.pptx').read_bytes(), b'previous output')

    def test_inconsistent_line_blank_modes_are_explicitly_rejected(self):
        chart = deepcopy(self.chart)
        for s, mode in zip(chart['series'], ('gap', 'connect')):
            s['type'] = 'line'; s.pop('fill'); s['nullHandling'] = mode
        with self.assertRaisesRegex(NativeExportError, 'share nullHandling'):
            model(chart, {})

    def test_invalid_data_and_pie_values_do_not_silently_disappear(self):
        for value in (True, 'nan', '1_000', float('inf'), 'text'):
            chart = deepcopy(self.chart); chart['data']['rows'][0][1] = value
            with self.subTest(value=value), self.assertRaises(NativeExportError): model(chart, {})
        pie = yaml.safe_load((FIXTURE / 'pages/03.page').read_text())['elements'][1]
        pie['data']['rows'][0][1] = -1
        with self.assertRaisesRegex(NativeExportError, 'nonnegative'): model(pie, {})

    def test_preview_uses_table_merge_anchors_and_normalized_chart_values(self):
        table = dict(elementId='table', elementType='table', bounds=[0,0,300,100],
                     columnWidths=[.5,.5], rowHeights=[.5,.5],
                     rows=[[dict(text='Merged', rowSpan=2), dict(text='B1')], [dict(text='B2')]],
                     style=dict(firstRowStyle=dict(color='#FF0000')))
        data = preview(dict(elements=[table, self.chart]), {})
        cells = data['table']['cells']
        self.assertEqual(len(cells), 3)
        self.assertEqual(cells[0]['rowSpan'], 2)
        self.assertEqual(cells[2]['sourceIndex'], 0)
        self.assertEqual(cells[0]['style']['color'], '#FF0000')
        self.assertEqual(data[self.chart['elementId']]['model']['series'][1]['values'][0], 9)
        bad = deepcopy(self.chart); bad['series'][0]['type'] = 'radar'
        self.assertIn('error', preview(dict(elements=[bad]), {})[bad['elementId']])


if __name__ == '__main__': unittest.main()
