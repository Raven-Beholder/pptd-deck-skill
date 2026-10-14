"""Editor HTTP/file boundary and draft-to-PPTX tests; no GUI automation."""
import hashlib
import base64
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'skills/pptd-deck-skill/scripts/local-export'))
from native_editor import create_server
from native_project import ConflictError, Project, page_value, parse
from native_workspace import import_folder, project_archive, save_export


class NativeEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pptd-editor-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        shutil.copytree(ROOT / 'skills/pptd-deck-skill/tests/fixtures/native', self.root)
        self.project = Project(self.root)
        self.loaded = self.project.load()
        self.first = self.loaded['pages'][0]

    def test_unchanged_save_preserves_source_bytes_and_draft_export_never_saves(self):
        page = self.first
        original = (self.root / page['path']).read_bytes()
        self.project.save(page['path'], page['text'], page['hash'], self.loaded['manifestHash'])
        self.assertEqual((self.root / page['path']).read_bytes(), original)
        text = page['text'].replace('Auditable export', 'DRAFT ONLY')
        blob = self.project.export({page['path']: text}, self.loaded['manifestHash'])
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn(b'DRAFT ONLY', archive.read('ppt/slides/slide1.xml'))
            self.assertEqual(len([n for n in archive.namelist() if n.startswith('ppt/slides/slide')]), 2)
        self.assertEqual((self.root / page['path']).read_bytes(), original)

    def test_page_creation_copy_remove_restore_and_export_options(self):
        paths=self.loaded['deck']['pages']
        before=(self.root/self.project.manifest).read_bytes()
        with self.assertRaises(ValueError):
            self.project.arrange_pages([paths[0], {'elements': [dict(elementId='bad')]}], self.loaded['manifestHash'])
        self.assertEqual(before,(self.root/self.project.manifest).read_bytes())
        self.assertFalse(list(self.root.glob('native-page-*.yaml')))
        added=self.project.arrange_pages([paths[0], self.first['page'], paths[1]], self.loaded['manifestHash'])
        new=added['pages'][1]
        self.assertEqual(new['page'],self.first['page'])
        self.assertNotEqual(new['path'],paths[0])
        with self.assertRaises(ConflictError): self.project.arrange_pages(paths,self.loaded['manifestHash'])
        removed=self.project.arrange_pages(paths,added['manifestHash'])
        self.assertTrue((self.root/new['path']).is_file())
        restored=self.project.arrange_pages([new['path'], *paths],removed['manifestHash'])
        hashes={p['path']:p['hash'] for p in restored['pages']}
        for transition in ('none','fade'):
            blob=self.project.export({},restored['manifestHash'],hashes,transition=transition)
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                slides=[n for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
                self.assertEqual(len(slides),3)
                self.assertEqual(b'<p:transition' in archive.read(slides[0]),transition=='fade')
        portable=project_archive(self.project,{},restored['manifestHash'],hashes)
        with zipfile.ZipFile(io.BytesIO(portable)) as archive:self.assertIn(new['path'],archive.namelist())
        for entries in ([],[paths[0],paths[0]],['../escape.yaml'],[self.project.manifest]):
            with self.assertRaises(ValueError):self.project.arrange_pages(entries,restored['manifestHash'])
        with self.assertRaises(ValueError):self.project.export({},restored['manifestHash'],hashes,embed_fonts=True)
        with self.assertRaises(ValueError):self.project.export({},restored['manifestHash'],hashes,transition='fake')

    def test_theme_draft_export_and_atomic_manifest_save(self):
        before = (self.root / self.loaded['manifest']).read_bytes()
        theme = json.loads(json.dumps(self.loaded['deck']['theme']))
        theme['colors']['ink'] = '#FE1234'
        theme['textStyles']['title'] = {'fontSize': 42, 'color': '$ink'}
        page = json.loads(json.dumps(self.first['page']))
        page['elements'][0]['content'] = {'text': 'THEME DRAFT', 'style': '$title'}
        blob = self.project.export({self.first['path']: json.dumps(page)}, self.loaded['manifestHash'], theme=theme)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            self.assertIn(b'FE1234', archive.read('ppt/slides/slide1.xml'))
            self.assertIn(b'sz="4200"', archive.read('ppt/slides/slide1.xml'))
        self.assertEqual((self.root / self.loaded['manifest']).read_bytes(), before)
        saved = self.project.save_theme(theme, self.loaded['manifestHash'])
        self.assertEqual(self.project.load()['deck']['theme'], theme)
        self.assertEqual(self.project.load()['manifestHash'], saved['manifestHash'])
        with self.assertRaises(ConflictError): self.project.save_theme({}, self.loaded['manifestHash'])

    def test_page_structure_does_not_refresh_away_an_external_edit_conflict(self):
        hashes={p['path']:p['hash'] for p in self.loaded['pages']}
        target=self.root/self.first['path']
        target.write_text(self.first['text']+'\n# external change\n')
        manifest=(self.root/self.project.manifest).read_bytes()
        with self.assertRaises(ConflictError):
            self.project.arrange_pages([*self.loaded['deck']['pages'],{'elements':[]}],self.loaded['manifestHash'],hashes)
        self.assertEqual((self.root/self.project.manifest).read_bytes(),manifest)
        self.assertFalse(list(self.root.glob('native-page-*.yaml')))
        self.assertTrue(target.read_text().endswith('# external change\n'))

    def test_explicit_relative_line_spacing_overrides_inherited_fixed_spacing(self):
        theme=json.loads(json.dumps(self.loaded['deck']['theme']))
        theme['textStyles']['fixed']={'lineHeightPx':40}
        page={'elements':[{'elementId':'title','elementType':'text','bounds':[0,0,300,100],
                          'content':{'style':'$fixed','text':'A', 'lineHeight':1.5}}]}
        blob=self.project.export({self.first['path']:json.dumps(page)},self.loaded['manifestHash'],theme=theme)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            slide=archive.read('ppt/slides/slide1.xml')
            self.assertIn(b'<a:spcPct val="150000"',slide)
            self.assertNotIn(b'<a:spcPts val="4000"',slide)

    def test_folder_import_and_portable_project_download(self):
        files = [dict(path=path.relative_to(self.root).as_posix(), data=base64.b64encode(path.read_bytes()).decode())
                 for path in self.root.rglob('*') if path.is_file()]
        workspace, imported = import_folder(files)
        self.addCleanup(workspace.cleanup)
        loaded = imported.load()
        text = loaded['pages'][0]['text'].replace('Auditable export', 'PORTABLE DRAFT')
        hashes = {p['path']: p['hash'] for p in loaded['pages']}
        data = project_archive(imported, {loaded['pages'][0]['path']: text}, loaded['manifestHash'], hashes)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('media/blocks.png', archive.namelist())
            self.assertIn(b'PORTABLE DRAFT', archive.read(loaded['pages'][0]['path']))
            self.assertIsNone(archive.testzip())
        self.assertNotIn('PORTABLE DRAFT', imported.load()['pages'][0]['text'])
        for name in ['../escape.pptd', '/absolute.pptd', 'folder/../escape.pptd', 'a\\b.pptd']:
            with self.assertRaises(ValueError): import_folder([dict(path=name, data='')])
        with self.assertRaises(ValueError): import_folder([files[0], files[0]])

    def test_stale_page_and_manifest_conflicts_preserve_external_changes(self):
        path = self.root / self.first['path']
        external = self.first['text'] + '\n# external change\n'
        path.write_bytes(external.encode('utf-8'))
        with self.assertRaises(ConflictError):
            self.project.save(self.first['path'], self.first['text'], self.first['hash'], self.loaded['manifestHash'])
        with self.assertRaises(ConflictError):
            self.project.export({}, self.loaded['manifestHash'], {p['path']: p['hash'] for p in self.loaded['pages']})
        self.assertEqual(path.read_bytes(), external.encode('utf-8'))
        (self.root / self.loaded['manifest']).write_text((self.root / self.loaded['manifest']).read_text() + '\n# external manifest edit\n')
        with self.assertRaises(ConflictError):
            self.project.export({}, self.loaded['manifestHash'])

    def test_write_scope_and_symlink_escape_are_rejected(self):
        (self.root / 'private.page').write_text('elements: []\n')
        with self.assertRaisesRegex(ValueError, 'existing manifest pages'):
            self.project.save('private.page', 'elements: []', '', self.loaded['manifestHash'])
        for name in ('../secret.png', '/etc/passwd', 'pages/../media/blocks.png', 'https://example.com/i.png', 'pages//01.page'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.project.path(name)
        (self.root / 'link.png').symlink_to(self.root / 'media/blocks.png')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.project.image('link.png')

    def test_unsupported_export_leaves_project_untouched_and_has_no_fallback(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            self.project.export({self.first['path']: 'elements:\n- elementId: video\n  elementType: video\n  bounds: [0,0,300,200]\n'}, self.loaded['manifestHash'])
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()})

    def test_yaml_limits_duplicate_keys_aliases_and_invalid_bounds(self):
        for source in ('elements: []\nelements: []', 'elements: &a [*a]', 'elements: []\nx: .nan',
                       'elements: []\nx: 9007199254740992', 'elements: []\nx: 2026-10-13',
                       'x: ' + '[' * 60 + '0' + ']' * 60, 'x: ' + 'a' * (1024 * 1024)):
            with self.subTest(source=source[:60]), self.assertRaises(ValueError):
                parse(source)
        with self.assertRaisesRegex(ValueError, 'bounds'):
            page_value(parse('elements: [{elementId: a, bounds: [0, 0, 0, 10]}]'))
        with self.assertRaisesRegex(ValueError, 'unique'):
            page_value(parse('elements: [{elementId: a, bounds: [0,0,1,1]}, {elementId: a, bounds: [0,0,1,1]}]'))

    def test_save_preserves_unknown_fields(self):
        text = self.first['text'] + '\nfutureFeature:\n  value: keep me\n'
        result = self.project.save(self.first['path'], text, self.first['hash'], self.loaded['manifestHash'])
        loaded = self.project.load()['pages'][0]
        self.assertEqual(loaded['page']['futureFeature'], {'value': 'keep me'})
        self.assertEqual(result['hash'], loaded['hash'])

    def test_image_import_is_content_addressed_and_draft_export_preserves_original_project(self):
        data = (self.root / 'media/blocks.png').read_bytes()
        encoded = base64.b64encode(data).decode('ascii')
        imported = self.project.import_image(encoded)
        self.assertEqual(imported, self.project.import_image(encoded))
        self.assertEqual(self.project.read(imported['path']), data)
        self.assertEqual(imported['width'], 120)
        self.assertEqual(imported['height'], 60)
        before = (self.root / self.first['path']).read_bytes()
        page = self.first['page']
        page['elements'].append(dict(elementId='imported', elementType='image', src=imported['path'], bounds=[10,10,100,100]))
        import yaml
        output = self.project.export({self.first['path']:yaml.safe_dump(page)}, self.loaded['manifestHash'])
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            self.assertIn(data, [archive.read(n) for n in archive.namelist() if n.startswith('ppt/media/')])
        self.assertEqual((self.root / self.first['path']).read_bytes(), before)
        for invalid in ('invalid!', base64.b64encode(b'not an image').decode()):
            with self.assertRaises(ValueError): self.project.import_image(invalid)
        (self.root / imported['path']).unlink()
        (self.root / imported['path']).symlink_to(self.root / 'media/blocks.png')
        with self.assertRaisesRegex(ValueError, 'symlink'): self.project.import_image(encoded)

    def test_inline_formula_html_entities_preserve_math_symbols(self):
        from native_text import RichText
        from native_math import Formula
        rich = RichText(r'<p>Compare \(a &lt; b\)</p>', {})
        formula = rich.paragraphs[0][1][1][0]
        self.assertIsInstance(formula, Formula)
        self.assertEqual(formula.source, 'a < b')

    def test_export_destination_collision_and_filename_boundaries(self):
        data = b'<svg xmlns="http://www.w3.org/2000/svg"><text>local</text></svg>'
        encoded = base64.b64encode(data).decode()
        first = save_export(encoded, str(self.root), 'review.svg')
        second = save_export(encoded, str(self.root), 'review.svg')
        self.assertEqual(Path(first['path']).read_bytes(), data)
        self.assertEqual(Path(second['path']).name, 'review (1).svg')
        original = self.root / 'original.svg'
        original.write_bytes(b'keep this file')
        (self.root / 'linked.svg').symlink_to(original)
        linked = save_export(encoded, str(self.root), 'linked.svg')
        self.assertEqual(Path(linked['path']).name, 'linked (1).svg')
        self.assertEqual(original.read_bytes(), b'keep this file')
        for filename in ('../out.svg', '/out.svg', '.hidden.svg', 'file.js', 'a\\b.svg', 'a:evil.svg'):
            with self.assertRaises(ValueError): save_export(encoded, str(self.root), filename)
        for directory in ('relative', str(self.root / 'missing')):
            with self.assertRaises(ValueError): save_export(encoded, directory, 'out.svg')
        with self.assertRaises(ValueError): save_export(encoded, str(self.root), 'out.png')
        self.assertFalse(list(self.root.glob('.pptd-export-*')))

    def test_loopback_binding_does_not_require_reverse_dns(self):
        from unittest.mock import patch
        with patch('socket.getfqdn',side_effect=AssertionError('reverse DNS is unnecessary')):
            server,url=create_server(self.project)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_name,'127.0.0.1')
        self.assertIn(str(server.server_port),url)

    def test_manifest_staging_write_failure_is_preserved_and_cleaned(self):
        from unittest.mock import patch
        import native_project
        target=self.root/self.loaded['manifest'];before=target.read_bytes()
        with patch.object(native_project.os,'fsync',side_effect=OSError('simulated fsync failure')):
            with self.assertRaisesRegex(OSError,'simulated fsync failure'):
                self.project._publish_manifest(before,self.loaded['manifestHash'])
        self.assertEqual(target.read_bytes(),before)
        self.assertEqual(list(self.root.glob('.pptd-manifest-*')),[])

    def test_http_edit_save_export_and_access_boundaries(self):
        server, url = create_server(self.project)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        parsed_url = urlsplit(url)
        def request(method, path, body=None, extra=None, auth=True):
            headers = {'Authorization': 'Bearer ' + parsed_url.fragment} if auth else {}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            headers.update(extra or {})
            connection = HTTPConnection('127.0.0.1', parsed_url.port, timeout=10)
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            result = response.status, response.read(), dict(response.getheaders())
            connection.close()
            return result
        try:
            code, html, headers = request('GET', '/', auth=False)
            self.assertEqual(code, 200)
            self.assertIn(b'PPTD Studio', html)
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            self.assertEqual(request('GET', '/api/project', auth=False)[0], 403)
            self.assertEqual(request('GET', '/api/fonts', auth=False)[0], 403)
            code, fonts, _ = request('GET', '/api/fonts')
            self.assertEqual(code, 200)
            self.assertIsInstance(json.loads(fonts)['families'], list)
            self.assertEqual(request('GET', '/api/project', extra={'Origin': 'https://example.com'})[0], 403)
            self.assertEqual(request('GET', '/api/project', extra={'Host': 'evil.example'})[0], 403)
            self.assertEqual(request('GET', '/neo-ppt/index.html')[0], 404)
            self.assertEqual(request('GET', '/api/image?path=../secret.png')[0], 400)
            code, image, headers = request('GET', '/api/image?path=media/blocks.png')
            self.assertEqual(code, 200)
            self.assertEqual(headers['Content-Type'], 'image/png')
            self.assertEqual(image, (self.root / 'media/blocks.png').read_bytes())
            (self.root / 'bad.png').write_bytes(b'\x89PNG\r\n\x1a\ninvalid header')
            self.assertEqual(request('GET', '/api/image?path=bad.png')[0], 400)
            code, data, _ = request('GET', '/api/project')
            self.assertEqual(code, 200)
            loaded = json.loads(data)
            first = loaded['pages'][0]
            # Model -> YAML -> save -> re-open -> PPTX: an end-to-end file contract.
            first['page']['elements'][0]['content']['text'] = 'HTTP round trip 中文'
            first['page']['elements'][0]['content'].update(fontFamily={'latin': 'Courier New', 'ea': 'Arial'},
                bold=True, italic=True, align=['center', 'middle'], backgroundColor='#FFFF00')
            first['page']['elements'][0]['bounds'][0] = 77
            first['page']['notes'] = '本页备注 HTTP round trip'
            code, preview, _ = request('POST', '/api/preview', {'page': first['page']})
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(preview), {'elements': {}})
            self.assertEqual(request('POST', '/api/preview', {'page': {'elements': 'invalid'}})[0], 400)
            first['page']['futureFeature'] = {'enabled': True}
            code, result, _ = request('POST', '/api/serialize', {'page': first['page']})
            self.assertEqual(code, 200)
            text = json.loads(result)['text']
            code, result, _ = request('POST', '/api/save', dict(path=first['path'], text=text, hash=first['hash'], manifestHash=loaded['manifestHash']))
            self.assertEqual(code, 200)
            self.assertEqual(self.project.load()['pages'][0]['page']['futureFeature'], {'enabled': True})
            # Unknown fields persist but the strict exporter explicitly rejects them.
            updated = self.project.load()
            export_body = dict(drafts={}, manifestHash=updated['manifestHash'], hashes={p['path']: p['hash'] for p in updated['pages']})
            self.assertEqual(request('POST', '/api/export', export_body)[0], 400)
            first['page'].pop('futureFeature')
            _, result, _ = request('POST', '/api/serialize', {'page': first['page']})
            export_body['drafts'] = {first['path']: json.loads(result)['text']}
            code, pptx, _ = request('POST', '/api/export', export_body)
            self.assertEqual(code, 200)
            with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
                slide = archive.read('ppt/slides/slide1.xml')
                self.assertIn('HTTP round trip 中文'.encode(), slide)
                self.assertIn(b'x="977900"', slide)  # 77 points in EMU.
                self.assertIn('本页备注 HTTP round trip'.encode(), archive.read('ppt/notesSlides/notesSlide1.xml'))
                self.assertIn(b'typeface="Courier New"', slide)
                self.assertIn(b'typeface="Arial"', slide)
                self.assertIn(b'b="1"', slide)
                self.assertIn(b'i="1"', slide)
                self.assertIn(b'algn="ctr"', slide)
                self.assertIn(b'<a:highlight>', slide)
            save_body = dict(data=base64.b64encode(pptx).decode(), directory=str(self.root), filename='http-export.pptx')
            self.assertEqual(request('POST', '/api/save-export', save_body, auth=False)[0], 403)
            self.assertEqual(request('POST', '/api/save-export', save_body, extra={'Origin':'https://example.com'})[0], 403)
            code, saved, _ = request('POST', '/api/save-export', save_body)
            self.assertEqual(code, 200)
            self.assertEqual(Path(json.loads(saved)['path']).read_bytes(), pptx)
            self.assertIn('futureFeature', self.project.load()['pages'][0]['page'])
            code, result, _ = request('POST', '/api/formula', {'source': r'\frac{a_1}{\sqrt{x}}'})
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(result)['expression']['children'][0]['kind'], 'fraction')
            self.assertEqual(request('POST', '/api/formula', {'source': r'\unknown{x}'})[0], 400)
            timeline_page = dict(elements=[dict(elementId='x', bounds=[0,0,10,10])], animations=[
                dict(elementId='x',effect='fade-in',trigger='onClick',durationMs=250),
                dict(elementId='x',effect='fade-out',trigger='afterPrevious',delayMs=100,durationMs=200)])
            code, result, _ = request('POST', '/api/playback', {'page':timeline_page})
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(result)['groups'][0]['events'][1]['start'], 350)
            self.assertEqual(request('POST', '/api/open-project', {'path':'relative/path'})[0], 400)
            code, result, _ = request('POST', '/api/open-project', {'path':str(self.root)})
            self.assertEqual(code, 200)
            self.assertNotEqual(json.loads(result)['projectId'], loaded['projectId'])
            self.assertEqual(request('GET', '/api/project', extra={'X-PPTD-Project':loaded['projectId']})[0], 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
