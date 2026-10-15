"""Portable font resources, EOT data, permissions and verified PPTX packages."""
import base64
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/local-export'))
from native_project_fonts import font_info, make_eot, read_eot, project_fonts
from native_project import Project, ConflictError
from native_workspace import project_archive, copy_project, import_folder
from native_validation import verify_output
from native_common import NS
from native_font_catalog import project_font_config


def test_font(family='Portable Test', *, bold=False, italic=False, rights=0, math=False):
    """Generated bounded SFNT data; no third-party font binary in fixtures."""
    strings = {1: family, 2: 'Bold Italic' if bold and italic else 'Bold' if bold else 'Italic' if italic else 'Regular',
               4: family + ' Face', 5: 'Version 1.0', 16: family}
    records, storage = b'', b''
    for identifier, text in strings.items():
        encoded = text.encode('utf-16-be')
        records += struct.pack('>6H', 3, 1, 1033, identifier, len(encoded), len(storage))
        storage += encoded
    names = struct.pack('>3H', 0, len(strings), 6 + len(records)) + records + storage
    os2 = bytearray(96)
    struct.pack_into('>HhHHH', os2, 0, 4, 600, 700 if bold else 400, 5, rights)
    struct.pack_into('>H', os2, 62, (0x20 if bold else 0x40) | int(italic))
    head = bytearray(54)
    struct.pack_into('>I', head, 12, 0x5F0F3CF5)
    tables = {b'OS/2': bytes(os2), b'head': bytes(head), b'name': names,
              b'maxp': struct.pack('>IH', 0x10000, 1), b'cmap': struct.pack('>HH', 0, 0),
              b'glyf': b'\0' * 10, b'loca': b'\0' * 4}
    if math:
        tables[b'MATH'] = struct.pack('>4H', 1, 0, 0, 0)
    offset = 12 + len(tables) * 16
    directory, body = b'', b''
    for tag, data in sorted(tables.items()):
        directory += struct.pack('>4sIII', tag, 0, offset, len(data))
        padded = data + b'\0' * (-len(data) % 4)
        offset += len(padded)
        body += padded
    return struct.pack('>4s4H', b'\x00\x01\x00\x00', len(tables), 0, 0, 0) + directory + body


class ProjectFontTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        (self.root / 'deck.pptd').write_text('version: v2\nsize: [960,540]\npages: [one.page]\n')
        page = dict(elements=[dict(elementId='text', elementType='text', bounds=[20,20,600,100],
                                   content=dict(fontFamily='Portable Test', text='<p>Regular <strong>Bold</strong></p>'))])
        (self.root / 'one.page').write_text(yaml.safe_dump(page))
        self.project = Project(self.root)

    def add(self, data, **kwargs):
        return self.project.import_font(base64.b64encode(data).decode(), self.project.load()['manifestHash'], **kwargs)

    def test_eot_full_payload_and_independent_header_contract(self):
        data = test_font(bold=True, italic=True, rights=0x108)
        eot = make_eot(data)
        self.assertEqual(struct.unpack_from('<4I', eot), (len(eot), len(data), 0x20001, 0))
        self.assertEqual(struct.unpack_from('<HH', eot, 32), (0x108, 0x504C))
        self.assertEqual(eot[-len(data):], data)
        self.assertEqual(read_eot(eot), data)
        corrupt = bytearray(eot)
        struct.pack_into('<I', corrupt, 4, len(data) - 1)
        with self.assertRaisesRegex(ValueError, 'length'):read_eot(bytes(corrupt))
        corrupt = bytearray(eot)
        struct.pack_into('<H', corrupt, 32, 0)
        with self.assertRaisesRegex(ValueError, 'permission'):read_eot(bytes(corrupt))

    def test_restricted_preview_only_bitmap_variable_and_corrupt_resources_fail(self):
        before = (self.root / 'deck.pptd').read_bytes()
        for rights in (2, 4, 0x208):
            with self.subTest(rights=rights), self.assertRaisesRegex(ValueError, '嵌入'):
                self.add(test_font(rights=rights))
        for data in (b'not a font', b'OTTO', test_font()[:100]):
            with self.subTest(data=data[:4]), self.assertRaises(ValueError):font_info(data)
        self.assertEqual((self.root / 'deck.pptd').read_bytes(), before)
        self.assertFalse((self.root / 'fonts').exists())

    def test_fonts_and_licenses_survive_copy_download_and_reimport(self):
        (self.root / 'OFL.txt').write_text('Generated fixture license notice')
        self.add(test_font(), license_path='OFL.txt')
        self.add(test_font(bold=True), license_path='OFL.txt')
        config = project_font_config(self.project)
        (self.root / 'fonts.json').write_text(json.dumps(config))
        loaded = self.project.load()
        self.assertEqual(len(loaded['fonts']), 2)
        self.assertEqual({font['weight'] for font in loaded['fonts']}, {400, 700})
        data = project_archive(self.project, {}, loaded['manifestHash'], {p['path']:p['hash'] for p in loaded['pages']})
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('OFL.txt', archive.namelist())
            self.assertEqual(json.loads(archive.read('fonts.json')), config)
            entries = [dict(path=name, data=base64.b64encode(archive.read(name)).decode()) for name in archive.namelist()]
        workspace, imported = import_folder(entries)
        self.addCleanup(workspace.cleanup)
        self.assertEqual(imported.load()['fonts'], loaded['fonts'])
        copied = copy_project(self.project, Path(self.temp.name))
        self.assertEqual(copied.load()['fonts'], loaded['fonts'])
        self.assertEqual(json.loads((copied.root / 'fonts.json').read_text()), config)
        copied_loaded = copied.load()
        copied.save('one.page', 'elements: []\n', copied_loaded['pages'][0]['hash'], copied_loaded['manifestHash'])
        self.assertNotEqual((copied.root / 'one.page').read_bytes(), (self.root / 'one.page').read_bytes())

    def test_complete_faces_embed_and_missing_bold_never_claims_success(self):
        (self.root / 'OFL.txt').write_text('Complete test notice <copyright> & license', encoding='utf-8')
        self.add(test_font(), license_path='OFL.txt')
        loaded = self.project.load()
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.glob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'Portable Test/bold'):
            self.project.export({}, loaded['manifestHash'], embed_fonts=True)
        self.add(test_font(bold=True), license_path='OFL.txt')
        loaded = self.project.load()
        blob = self.project.export({}, loaded['manifestHash'], embed_fonts=True)
        output = Path(self.temp.name) / 'embedded.pptx'
        output.write_bytes(blob)
        report = verify_output(output, expect_fonts=True)
        self.assertEqual(report['fontParts'], 2)
        self.assertEqual(report['embeddedFamilies'], ['Portable Test'])
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            doc = ET.fromstring(archive.read('ppt/presentation.xml'))
            faces = doc.find('p:embeddedFontLst/p:embeddedFont', NS)
            self.assertEqual([child.tag.rsplit('}',1)[-1] for child in faces], ['font','regular','bold'])
            self.assertEqual(len([name for name in archive.namelist() if name.startswith('ppt/fonts/')]), 2)
            notices = [name for name in archive.namelist() if name.startswith('customXml/fontLicense')]
            self.assertEqual(len(notices), 1)
            notice = ET.fromstring(archive.read(notices[0]))
            self.assertEqual(notice.find('{urn:pptd:font-license}notice').text, (self.root/'OFL.txt').read_text())
        no_embed = self.project.export({}, loaded['manifestHash'])
        with zipfile.ZipFile(io.BytesIO(no_embed)) as archive:
            self.assertFalse(any(name.startswith('ppt/fonts/') for name in archive.namelist()))
        self.assertEqual(hashlib.sha256((self.root/'one.page').read_bytes()).hexdigest(), before['one.page'])

    def test_project_math_family_embeds_regular_face_and_text_default_ignores_math(self):
        with self.assertRaisesRegex(ValueError, 'MATH'):
            self.project.import_font_bundle([test_font('Portable Math')], self.project.load()['manifestHash'], role='math')
        self.project.import_font_bundle([test_font('Portable Math', math=True)], self.project.load()['manifestHash'], role='math')
        self.add(test_font())
        page = dict(elements=[dict(elementId='math', elementType='text', bounds=[20,20,600,100],
                                  content=dict(text=r'Formula \(x^2 + \frac{a}{b}\)'))])
        loaded = self.project.load()
        self.project.save('one.page', yaml.safe_dump(page), loaded['pages'][0]['hash'], loaded['manifestHash'])
        loaded = self.project.load()
        blob = self.project.export({}, loaded['manifestHash'], embed_fonts=True)
        target = Path(self.temp.name) / 'math.pptx'
        target.write_bytes(blob)
        report = verify_output(target, expect_fonts=True)
        self.assertEqual(report['embeddedFamilies'], ['Portable Math', 'Portable Test'])
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            slide = archive.read('ppt/slides/slide1.xml')
            self.assertIn(b'typeface="Portable Math"', slide)
            self.assertIn(b'typeface="Portable Test"', slide)
            self.assertNotIn(b'Cambria Math', slide)
            self.assertIn(b'typeface="Portable Test"', archive.read('ppt/theme/theme1.xml'))
        config = project_font_config(self.project)
        self.assertEqual(set(config['families']), {'Portable Test'})
        self.assertEqual(config['math']['regular'], loaded['deck']['customFonts'][0]['src'])

    def test_host_font_config_is_omitted_and_escaping_config_is_rejected(self):
        self.add(test_font())
        config = self.root / 'fonts.json'
        config.write_text(json.dumps({'families': {'Host': {'regular': '/host/private/font.ttf'}}}))
        copied = copy_project(self.project, Path(self.temp.name))
        self.assertFalse((copied.root / 'fonts.json').exists())
        config.write_text(json.dumps({'families': {'Escape': {'regular': '../outside.ttf'}}}))
        with self.assertRaisesRegex(ValueError, 'inside'):
            copy_project(self.project, Path(self.temp.name))

    def test_font_path_escape_alias_mismatch_and_stale_import_preserve_source(self):
        result = self.add(test_font())
        stale = self.project.load()['manifestHash']
        (self.root / 'deck.pptd').write_text((self.root / 'deck.pptd').read_text() + '# external\n')
        with self.assertRaises(ConflictError):
            self.project.import_font(base64.b64encode(test_font(bold=True)).decode(), stale)
        entry = result['customFonts'][0]
        for source in ('../escape.ttf', '/tmp/font.ttf', 'https://example.com/font.ttf'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                project_fonts(self.root, [dict(entry, src=source)])
        with self.assertRaisesRegex(ValueError, 'match'):
            project_fonts(self.root, [dict(entry, family='False Alias')])
        link = self.root / 'link.ttf'
        link.symlink_to(self.root / entry['src'])
        with self.assertRaisesRegex(ValueError, 'symlink'):
            project_fonts(self.root, [dict(entry, src='link.ttf')])


if __name__ == '__main__':unittest.main()
