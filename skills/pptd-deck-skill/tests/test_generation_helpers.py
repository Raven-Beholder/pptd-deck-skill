"""Regression cases from blank slides, style fallback and font/path guessing."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

import yaml
from PIL import Image

import test_pipeline
import pipeline
import auto_fonts
import template_samples
import native_cli
from font_support import FontRegistry
from native_fonts import font_faces
from native_common import NS
from native_export_audit import verify_content
from native_project import Project
from native_workspace import project_archive


@unittest.skipUnless(test_pipeline.FONT, 'installed QA font unavailable')
class GenerationHelperTests(unittest.TestCase):
    setUp = test_pipeline.PipelineTests.setUp
    tearDown = test_pipeline.PipelineTests.tearDown
    args = test_pipeline.PipelineTests.args
    run_stage = test_pipeline.PipelineTests.run_stage
    write_page = test_pipeline.PipelineTests.write_page

    def records(self):
        return [dict(record, path=str(test_pipeline.FONT.resolve())) for record in font_faces(test_pipeline.FONT)]

    def source(self):
        source = self.root / 'source.pptx'
        native_cli.export(self.manifest, source)
        return source

    def mutate(self, path, change):
        with ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        doc = ET.fromstring(files['ppt/slides/slide1.xml'])
        change(doc)
        files['ppt/slides/slide1.xml'] = ET.tostring(doc)
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)

    def test_offline_init_uses_real_family_and_font_paths(self):
        args = self.args()
        args.project = str(self.root / 'automatic')
        args.theme = 'wine-red-data'; args.topic = 'Test'; args.pages = 1; args.research = False
        args.body_font = args.math_font = args.family = None
        with patch.object(auto_fonts, 'inventory', return_value=self.records()):
            self.run_stage(pipeline.init, args)
        deck = yaml.safe_load((Path(args.project) / 'deck.pptd').read_text())
        config = json.loads((Path(args.project) / 'fonts.json').read_text())
        family = deck['theme']['textStyles']['body']['fontFamily']
        self.assertIn(family, config['families'])
        self.assertTrue(Path(config['families'][family]['regular']['path']).is_file())
        FontRegistry(config, Path(args.project))

    def test_missing_config_is_generated_without_source_edits_or_network(self):
        (self.root / 'fonts.json').unlink()
        before = self.manifest.read_bytes()
        with patch.object(auto_fonts, 'inventory', return_value=self.records()):
            self.run_stage(pipeline.prepare)
        self.assertEqual(before, self.manifest.read_bytes())
        self.assertIn(self.family, pipeline.read(self.root / 'fonts.json')['families'])
        with self.assertRaisesRegex(ValueError, 'exists'):
            self.run_stage(pipeline.fonts_config)

    def test_unavailable_declared_font_is_not_silently_replaced(self):
        self.page['elements'][0]['content']['fontFamily'] = 'Missing Template Typeface'
        self.write_page(); (self.root / 'fonts.json').unlink()
        before = (self.root / 'pages/01.page').read_bytes()
        with patch.object(auto_fonts, 'inventory', return_value=self.records()):
            with self.assertRaisesRegex(ValueError, 'available replacement'):
                self.run_stage(pipeline.fonts_config)
        self.assertFalse((self.root / 'fonts.json').exists())
        self.assertEqual(before, (self.root / 'pages/01.page').read_bytes())

    def test_font_coverage_failure_is_actionable(self):
        with self.assertRaisesRegex(ValueError, 'no installed font covers'):
            auto_fonts.select(self.records(), '\U0010ffff')

    def test_font_mapping_uses_rich_text_table_and_math_characters(self):
        self.page['elements'][0]['content']['text'] = r'<p><strong>Value</strong> \(\alpha+x^2\)</p>'
        self.page['elements'].append({'elementId': 'table', 'elementType': 'table', 'bounds': [20, 150, 400, 100],
                                      'columnWidths': [1], 'rowHeights': [1],
                                      'rows': [[{'text': 'Table value', 'fontFamily': self.family}]]})
        needed, math_text = auto_fonts.requirements(self.deck, [self.page], self.family)
        self.assertIn('Table value', needed[self.family]); self.assertIn('α', math_text)
        self.assertNotIn('alpha', math_text)
        with patch.object(auto_fonts, 'inventory', return_value=self.records()):
            config = auto_fonts.configure(self.root, self.deck, [self.page])
        FontRegistry(config, self.root)

    def test_samples_reuse_assets_text_geometry_and_source_provenance(self):
        Image.new('RGB', (20, 10), '#0080C0').save(self.root / 'logo.png')
        self.page['elements'].insert(0, {'elementId': 'logo', 'elementType': 'image', 'bounds': [700, 20, 100, 50], 'src': 'logo.png', 'fit': {'mode': 'fill'}})
        self.page['elements'][1]['content'].update(fontSize=30, bold=True)
        self.write_page()
        source = self.source(); before = source.read_bytes()
        destination = self.root / 'starter'
        with patch.object(auto_fonts, 'inventory', return_value=self.records()):
            result = template_samples.create(source, destination)
        self.assertEqual(result['pages'], 1)
        self.assertEqual(before, (destination / 'template/source.pptx').read_bytes())
        deck = yaml.safe_load((destination / 'deck.pptd').read_text())
        page = yaml.safe_load((destination / deck['pages'][0]).read_text())
        text = next(e for e in page['elements'] if e['elementType'] == 'text')
        self.assertEqual(text['bounds'], [30, 30, 500, 60])
        self.assertIn('Test source', text['content']['text'])
        self.assertIn('font-size:30px', text['content']['text'])
        self.assertIn('font-weight:bold', text['content']['text'])
        image = next(e for e in page['elements'] if e['elementType'] == 'image')
        self.assertTrue((destination / image['src']).is_file())
        native_cli.export(destination / 'deck.pptd', self.root / 'starter.pptx')
        report = pipeline.read(destination / 'template-samples.json')
        self.assertNotIn(str(self.root), json.dumps(report))
        project = Project(destination); loaded = project.load()
        portable = project_archive(project, {}, loaded['manifestHash'], {page['path']: page['hash'] for page in loaded['pages']})
        with ZipFile(io.BytesIO(portable)) as archive:
            self.assertIn('template-samples.json', archive.namelist())
            self.assertEqual(archive.read('template/source.pptx'), before)
        (destination / 'template/source.pptx').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'template reference changed'):
            project_archive(project, {}, loaded['manifestHash'], {page['path']: page['hash'] for page in loaded['pages']})
        with self.assertRaisesRegex(ValueError, 'never overwritten'):
            template_samples.create(source, destination)

    def test_unsupported_template_object_is_recorded_and_input_preserved(self):
        self.page['elements'].append({'elementId': 'table', 'elementType': 'table', 'bounds': [20, 150, 400, 100],
                                      'columnWidths': [1], 'rowHeights': [1], 'rows': [['Preserve original']]})
        self.write_page(); source = self.source(); destination = self.root / 'starter'
        with patch.object(auto_fonts, 'inventory', return_value=self.records()):
            template_samples.create(source, destination)
        report = pipeline.read(destination / 'template-samples.json')
        self.assertTrue(any('graphicFrame' in issue['reason'] for issue in report['issues']))
        self.assertEqual(source.read_bytes(), (destination / 'template/source.pptx').read_bytes())

    def test_text_loss_and_style_fallback_are_rejected_after_export(self):
        self.page['elements'][0]['content'] = {'text': 'Test source', 'style': '$title'}
        self.deck['theme']['textStyles']['title'] = {'fontSize': 30, 'bold': True, 'fontFamily': self.family}
        self.manifest.write_text(yaml.safe_dump(self.deck)); self.write_page()
        source = self.source(); baseline = source.read_bytes()
        def change_style(doc):
            props = doc.find('.//a:rPr', NS); props.set('sz', '1600'); props.set('b', '0')
        self.mutate(source, change_style)
        with self.assertRaisesRegex(ValueError, 'style fallback'):
            verify_content(self.manifest, source)
        source.write_bytes(baseline)
        self.mutate(source, lambda doc: setattr(doc.find('.//a:t', NS), 'text', ''))
        with self.assertRaisesRegex(ValueError, 'possible blank page'):
            verify_content(self.manifest, source)

    def test_formula_and_table_audit_avoids_compatibility_double_count(self):
        self.page['elements'][0]['content']['text'] = r'Test \(x^2+1\)'
        self.page['elements'].append({'elementId': 'table', 'elementType': 'table', 'bounds': [20, 150, 400, 100],
                                      'columnWidths': [.5, .5], 'rowHeights': [1],
                                      'rows': [[{'text': r'\(\alpha\)', 'bold': True}, {'text': '<p><strong>Value</strong></p>', 'fontSize': 22}]]})
        self.write_page(); source = self.source()
        report = verify_content(self.manifest, source)
        self.assertEqual(report['pages'][0]['mathObjects'], 2)
        self.assertEqual(report['status'], 'passed')

    def test_audit_failure_preserves_previous_output(self):
        output = self.root / 'result.pptx'
        native_cli.export(self.manifest, output); before = output.read_bytes()
        original = native_cli.export_native
        def broken(*args, **kwargs):
            result = original(*args, **kwargs)
            self.mutate(args[1], lambda doc: setattr(doc.find('.//a:t', NS), 'text', ''))
            return result
        with patch.object(native_cli, 'export_native', side_effect=broken):
            with self.assertRaisesRegex(ValueError, 'possible blank page'):
                native_cli.export(self.manifest, output, force=True)
        self.assertEqual(before, output.read_bytes())

    def test_editor_export_also_rejects_lost_content(self):
        project = Project(self.root); loaded = project.load()
        original = native_cli.export_native
        def broken(*args, **kwargs):
            result = original(*args, **kwargs)
            self.mutate(args[1], lambda doc: setattr(doc.find('.//a:t', NS), 'text', ''))
            return result
        with patch('native_project.export_native', side_effect=broken):
            with self.assertRaisesRegex(ValueError, 'possible blank page'):
                project.export({}, loaded['manifestHash'], {page['path']: page['hash'] for page in loaded['pages']})


if __name__ == '__main__':
    unittest.main()
