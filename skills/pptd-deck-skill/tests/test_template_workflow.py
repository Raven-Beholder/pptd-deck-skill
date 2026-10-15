"""Template provenance, relationship extraction and fail-closed acceptance."""
import io
import shutil
import unittest
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
from unittest.mock import patch

import test_pipeline
import pipeline
import template_workflow as workflow
from native_common import NS
from native_project import Project
from native_workspace import project_archive
from PIL import Image


@unittest.skipUnless(test_pipeline.FONT, 'installed test font unavailable')
class TemplateWorkflowTests(unittest.TestCase):
    setUp = test_pipeline.PipelineTests.setUp
    tearDown = test_pipeline.PipelineTests.tearDown
    args = test_pipeline.PipelineTests.args
    write_page = test_pipeline.PipelineTests.write_page
    run_stage = test_pipeline.PipelineTests.run_stage

    def fixture(self):
        source = self.root / 'sample.pptx'
        pipeline.native_export(self.manifest, source, 'fade')
        self.run_stage(pipeline.prepare)
        shutil.copyfile(self.root / '.pipeline/images/01.png', self.root / 'ref.png')
        pipeline.save(self.root / 'references.json', {'renderer': 'Synthetic Pillow fixture; no Office claim', 'pages': ['ref.png']})
        return source

    def bind(self):
        return workflow.import_template(self.root, self.deck['pages'], self.fixture(), self.root / 'references.json')

    def approve(self, passed=True):
        decisions = [{'page': 'pages/01.page', 'sourcePage': 1, 'passed': passed,
                      'note': 'Synthetic fixture acceptance exercises the gate, not a human visual check.'}]
        pipeline.save(self.root / 'decisions.json', decisions)
        args = self.args(); args.template_decisions = str(self.root / 'decisions.json')
        self.run_stage(pipeline.review, args)

    def rewrite_zip(self, source, modify):
        with ZipFile(source) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        modify(files)
        with ZipFile(source, 'w', ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)

    def test_import_compare_review_export_and_portable_copy(self):
        contract = self.bind()
        self.assertEqual(workflow.digest(self.root / contract['source']), workflow.digest(self.root / 'sample.pptx'))
        self.assertNotIn(str(self.root), (self.root / 'template.json').read_text())
        layout = workflow.read(self.root / contract['layouts'])
        self.assertEqual(layout['slides'][0]['objects'][0]['boundsPt'], [30, 30, 500, 60])
        self.assertEqual(len(layout['layouts']), 1)
        self.assertEqual(len(layout['masters']), 1)
        self.assertEqual(len(layout['themes']), 1)
        self.run_stage(pipeline.prepare)
        report = pipeline.read(self.root / '.pipeline/render.json')
        pair = report['templateComparison']['pages'][0]
        self.assertEqual(pair['sourcePage'], 1)
        self.assertTrue((self.root / pair['pair']).is_file())
        self.approve(); self.run_stage(pipeline.export)
        project = Project(self.root); loaded = project.load()
        data = project_archive(project, {}, loaded['manifestHash'], {p['path']: p['hash'] for p in loaded['pages']})
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('template.json', archive.namelist())
            self.assertTrue(set(contract['files']).issubset(archive.namelist()))
            self.assertNotIn('.pipeline/review.json', archive.namelist())

    def test_missing_or_failed_decisions_revoke_old_approval(self):
        self.bind(); self.run_stage(pipeline.prepare); self.approve()
        with self.assertRaisesRegex(ValueError, 'template-decisions'):
            self.run_stage(pipeline.review)
        self.assertFalse((self.root / '.pipeline/review.json').exists())
        with self.assertRaises(OSError):
            self.run_stage(pipeline.export)
        self.approve()
        with self.assertRaisesRegex(ValueError, 'Review found issues'):
            self.approve(False)
        with self.assertRaisesRegex(ValueError, 'marked issues'):
            self.run_stage(pipeline.export)
        self.approve(); self.run_stage(pipeline.export)

    def test_structural_mode_cannot_bypass_template_acceptance(self):
        self.bind()
        args = self.args(); args.structural_only = True; args.reason = 'Unavailable image viewer'
        with self.assertRaisesRegex(ValueError, 'requires rendered'):
            self.run_stage(pipeline.prepare, args)
        self.assertFalse((self.root / '.pipeline/render.json').exists())
        self.run_stage(pipeline.prepare)
        args.mode = 'structural'
        with self.assertRaisesRegex(ValueError, 'visual mode'):
            self.run_stage(pipeline.review, args)

    def test_comparison_and_reference_changes_block_export(self):
        contract = self.bind(); self.run_stage(pipeline.prepare); self.approve()
        report = pipeline.read(self.root / '.pipeline/render.json')
        pair = self.root / report['templateComparison']['pages'][0]['pair']
        pair.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'comparison image changed'):
            self.run_stage(pipeline.export)
        self.run_stage(pipeline.prepare); self.approve()
        (self.root / contract['references'][0]['image']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'template input changed'):
            self.run_stage(pipeline.export)

    def test_incomplete_decisions_and_stale_mapping_fail(self):
        self.bind(); self.run_stage(pipeline.prepare)
        comparison = pipeline.read(self.root / '.pipeline/render.json')['templateComparison']
        for value in ([], [{'page': 'pages/01.page', 'sourcePage': 2, 'passed': True, 'note': 'checked'}],
                      [{'page': 'pages/01.page', 'sourcePage': 1, 'passed': 'true', 'note': 'checked'}]):
            with self.assertRaises(ValueError):
                workflow.decisions(value, comparison)
        contract = workflow.read(self.root / 'template.json')
        contract['mapping'][0]['page'] = 'pages/renamed.page'
        pipeline.save(self.root / 'template.json', contract)
        with self.assertRaisesRegex(ValueError, 'mapping'):
            self.run_stage(pipeline.prepare)

    def test_import_is_transactional_and_rejects_overwrite(self):
        source = self.fixture()
        before = self.manifest.read_bytes()
        Image.new('RGB', (100, 100)).save(self.root / 'ref.png')
        with self.assertRaisesRegex(ValueError, 'aspect ratio'):
            workflow.import_template(self.root, self.deck['pages'], source, self.root / 'references.json')
        self.assertFalse((self.root / 'template.json').exists())
        self.assertEqual(list((self.root / 'template').iterdir()), [])
        self.assertEqual(before, self.manifest.read_bytes())
        shutil.copyfile(self.root / '.pipeline/images/01.png', self.root / 'ref.png')
        workflow.import_template(self.root, self.deck['pages'], source, self.root / 'references.json')
        with self.assertRaisesRegex(ValueError, 'already bound'):
            workflow.import_template(self.root, self.deck['pages'], source, self.root / 'references.json')

    def test_order_is_relationship_based_and_bounds_inherit_from_master(self):
        source = self.fixture()
        def modify(files):
            presentation = ET.fromstring(files['ppt/presentation.xml'])
            ids = presentation.find('p:sldIdLst', NS)
            entry = ET.fromstring(ET.tostring(ids[0])); entry.set('id', '999'); entry.set('{%s}id' % NS['r'], 'new-slide')
            ids.insert(0, entry)
            files['ppt/presentation.xml'] = ET.tostring(presentation)
            rels = ET.fromstring(files['ppt/_rels/presentation.xml.rels'])
            ET.SubElement(rels, '{%s}Relationship' % NS['rel'], Id='new-slide', Type=NS['r'] + '/slide', Target='slides/unusual.xml')
            files['ppt/_rels/presentation.xml.rels'] = ET.tostring(rels)
            slide = ET.fromstring(files['ppt/slides/slide1.xml'])
            shape = slide.find('p:cSld/p:spTree/p:sp', NS)
            ET.SubElement(shape.find('p:nvSpPr/p:nvPr', NS), '{%s}ph' % NS['p'], type='title', idx='7')
            shape.find('p:spPr', NS).remove(shape.find('p:spPr/a:xfrm', NS))
            files['ppt/slides/unusual.xml'] = ET.tostring(slide)
            files['ppt/slides/_rels/unusual.xml.rels'] = files['ppt/slides/_rels/slide1.xml.rels']
            parent_shape = ET.fromstring(ET.tostring(shape))
            for name, with_bounds in [('ppt/slideLayouts/slideLayout1.xml', False), ('ppt/slideMasters/slideMaster1.xml', True)]:
                doc = ET.fromstring(files[name]); copy = ET.fromstring(ET.tostring(parent_shape))
                if with_bounds:
                    xfrm = ET.SubElement(copy.find('p:spPr', NS), '{%s}xfrm' % NS['a'])
                    ET.SubElement(xfrm, '{%s}off' % NS['a'], x='12700', y='25400')
                    ET.SubElement(xfrm, '{%s}ext' % NS['a'], cx='127000', cy='254000')
                doc.find('p:cSld/p:spTree', NS).append(copy); files[name] = ET.tostring(doc)
        self.rewrite_zip(source, modify)
        result = workflow.extract(source)
        self.assertEqual(result['slides'][0]['part'], 'ppt/slides/unusual.xml')
        shape = result['slides'][0]['objects'][0]
        self.assertEqual(shape['boundsPt'], [1, 2, 10, 20])
        self.assertEqual(shape['boundsSource'], 'ppt/slideMasters/slideMaster1.xml')

    def test_bad_zip_xml_external_slide_and_traversal_fail(self):
        source = self.fixture(); original = source.read_bytes()
        for mutation in [
            lambda files: files.update({'../escape.xml': b'x'}),
            lambda files: files.update({'ppt/presentation.xml': b'<!DOCTYPE x [<!ENTITY x "x">]><x/>'}),
            lambda files: files.update({'ppt/presentation.xml': b'<broken>'}),
            lambda files: files.pop('ppt/slides/slide1.xml'),
        ]:
            source.write_bytes(original); self.rewrite_zip(source, mutation)
            with self.assertRaises(ValueError): workflow.extract(source)
        source.write_bytes(b'not a zip')
        with self.assertRaisesRegex(ValueError, 'invalid template package'): workflow.extract(source)

    def test_external_slide_duplicate_members_and_xml_limit_fail(self):
        source = self.fixture(); original = source.read_bytes()
        def external(files):
            rels = ET.fromstring(files['ppt/_rels/presentation.xml.rels'])
            for rel in rels:
                if rel.get('Type').endswith('/slide'):
                    rel.set('TargetMode', 'External'); rel.set('Target', 'https://example.invalid/slide.xml')
            files['ppt/_rels/presentation.xml.rels'] = ET.tostring(rels)
        self.rewrite_zip(source, external)
        with self.assertRaisesRegex(ValueError, 'slide relationship'): workflow.extract(source)
        source.write_bytes(original)
        with patch.object(workflow, 'XML_LIMIT', 1):
            with self.assertRaisesRegex(ValueError, 'XML exceeds'): workflow.extract(source)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with ZipFile(source, 'a') as archive: archive.writestr('ppt/presentation.xml', b'<x/>')
        with self.assertRaisesRegex(ValueError, 'duplicate'): workflow.extract(source)

    def test_potx_source_is_preserved_and_missing_reference_is_rejected(self):
        source = self.fixture(); potx = source.with_suffix('.potx'); source.rename(potx)
        refs = self.root / 'references.json'
        pipeline.save(refs, {'renderer': 'fixture', 'pages': []})
        with self.assertRaisesRegex(ValueError, 'one image per source slide'):
            workflow.import_template(self.root, self.deck['pages'], potx, refs)
        pipeline.save(refs, {'renderer': 'fixture', 'pages': ['ref.png']})
        value = workflow.import_template(self.root, self.deck['pages'], potx, refs)
        self.assertTrue(value['source'].endswith('.potx'))
        self.assertEqual((self.root / value['source']).read_bytes(), potx.read_bytes())

    def test_template_mapping_edit_invalidates_approval_and_candidate_size_is_checked(self):
        self.bind(); self.run_stage(pipeline.prepare); self.approve()
        self.deck['size'] = [960, 720]
        import yaml
        self.manifest.write_text(yaml.safe_dump(self.deck))
        with self.assertRaisesRegex(ValueError, 'stale'): self.run_stage(pipeline.export)
        with self.assertRaisesRegex(ValueError, 'aspect ratio'): self.run_stage(pipeline.prepare)

    def test_explicit_mapping_required_for_different_page_counts(self):
        source = self.fixture()
        pages = ['pages/01.page', 'pages/02.page']
        with self.assertRaisesRegex(ValueError, 'explicit --mapping'):
            workflow.import_template(self.root, pages, source, self.root / 'references.json')
        mapping = [{'page': page, 'sourcePage': 1} for page in pages]
        result = workflow.import_template(self.root, pages, source, self.root / 'references.json', mapping)
        self.assertEqual(result['mapping'], mapping)


if __name__ == '__main__':
    unittest.main()
