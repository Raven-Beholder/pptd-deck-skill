"""Pinned OFL downloads, portable generation and authenticated font transport."""
import base64
import contextlib
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pipeline
import native_font_catalog as fonts
from native_editor import create_server
from native_project import Project
from test_native_project_fonts import test_font


def resource(data, name):
    return dict(url='https://raw.githubusercontent.com/test/fonts/' + 'a'*40 + '/' + name,
                bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class FontCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        (self.root/'deck.pptd').write_text('version: v2\nsize: [960,540]\npages: [one.page]\n')
        (self.root/'one.page').write_text('elements: []\n')
        self.project = Project(self.root)

    def test_catalog_is_ofl_pinned_and_has_complete_resource_metadata(self):
        entries = fonts.catalog()
        public = fonts.public_catalog()
        self.assertEqual(len(entries), 16)
        self.assertEqual(len({entry['id'] for entry in entries}), len(entries))
        self.assertEqual(len({entry['family'] for entry in entries}), len(entries))
        self.assertEqual(sum(entry['faces'] for entry in public), 53)
        for entry in entries:
            self.assertEqual(entry['license'], 'OFL-1.1')
            for item in [entry['notice'], *entry['fonts']]:
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
                self.assertGreater(item['bytes'], 0)
                self.assertTrue(re.search(r'/[0-9a-f]{40}/|/releases/download/v[0-9.]+/', item['url']), item['url'])
                if item.get('member'):
                    self.assertRegex(item['memberSha256'], r'^[0-9a-f]{64}$')
                    if item in entry['fonts']:
                        self.assertGreater(item['fontBytes'], 0)

    def test_download_hashes_lengths_and_zip_members_before_install(self):
        raw = test_font()
        item = resource(raw, 'font.ttf')
        with patch.object(fonts, 'urlopen', return_value=io.BytesIO(raw)) as download:
            cache = {}
            self.assertEqual(fonts.download_resource(item, cache), raw)
            self.assertEqual(fonts.download_resource(item, cache), raw)
            self.assertEqual(download.call_count, 1)
        for payload in (raw[:-1], raw + b'extra', b'X' * len(raw)):
            with patch.object(fonts, 'urlopen', return_value=io.BytesIO(payload)), self.assertRaisesRegex(ValueError, '校验'):
                fonts.download_resource(item, {})
        with patch.object(fonts, 'urlopen') as download, self.assertRaisesRegex(ValueError, 'allowlisted'):
            fonts.download_resource(dict(item, url='https://example.com/font.ttf'), {})
        download.assert_not_called()
        container = io.BytesIO()
        with zipfile.ZipFile(container, 'w') as archive:
            archive.writestr('fonts/regular.ttf', raw)
        zipped = container.getvalue()
        item = dict(resource(zipped, 'bundle.zip'), member='fonts/regular.ttf', memberSha256=hashlib.sha256(raw).hexdigest())
        with patch.object(fonts, 'urlopen', return_value=io.BytesIO(zipped)):
            self.assertEqual(fonts.download_resource(item, {}), raw)
        with patch.object(fonts, 'urlopen', return_value=io.BytesIO(zipped)), self.assertRaisesRegex(ValueError, '校验'):
            fonts.download_resource(dict(item, memberSha256='0'*64), {})

    def test_failed_bundle_preserves_manifest_and_notice_is_retained(self):
        regular, bold = test_font(), test_font(bold=True)
        notice = b'Generated fixture copyright and full license notice'
        entry = dict(id='fixture', family='Portable Test', license='OFL-1.1', role='text',
                     fonts=[resource(regular, 'regular.ttf'), resource(bold, 'bold.ttf')], notice=resource(notice, 'OFL.txt'))
        before = (self.root/'deck.pptd').read_bytes()
        with patch.object(fonts, 'catalog', return_value=[entry]), patch.object(fonts, 'urlopen', side_effect=[io.BytesIO(notice), io.BytesIO(regular), io.BytesIO(bold[:-1])]):
            with self.assertRaisesRegex(ValueError, '校验'):
                fonts.install_family(self.project, 'fixture', self.project.load()['manifestHash'])
        self.assertEqual((self.root/'deck.pptd').read_bytes(), before)
        self.assertFalse((self.root/'fonts').exists())
        with patch.object(fonts, 'catalog', return_value=[entry]), patch.object(fonts, 'urlopen', side_effect=[io.BytesIO(notice), io.BytesIO(regular), io.BytesIO(bold)]):
            fonts.install_family(self.project, 'fixture', self.project.load()['manifestHash'])
        custom = self.project.load()['deck']['customFonts']
        self.assertEqual(len(custom), 2)
        self.assertEqual((self.root/custom[0]['license']).read_bytes(), notice)
        self.assertEqual(set(fonts.project_font_config(self.project)['families']['Portable Test']), {'regular', 'bold'})

    def test_ofl_init_maps_real_faces_and_separate_math_role(self):
        destination = Path(self.temp.name)/'generated'
        choices = [dict(id='text', family='Portable Test'), dict(id='math', family='Portable Math', role='math')]
        installed = []
        def install(project, identifier, manifest_hash):
            installed.append(identifier)
            data = [test_font(), test_font(bold=True)] if identifier == 'text' else [test_font('Portable Math', math=True)]
            return project.import_font_bundle(data, manifest_hash, notice='Complete fixture notice',
                                              notice_name=identifier, role='math' if identifier == 'math' else 'text')
        args = SimpleNamespace(project=str(destination), pages=2, theme='wine-red-data', topic='Portable', research=False,
                               font_family='text', extra_font=['text'], math_family='math', body_font=None, math_font=None, family=None)
        with patch.object(pipeline, 'font_catalog', return_value=choices), patch.object(pipeline, 'install_family', side_effect=install), contextlib.redirect_stdout(io.StringIO()):
            pipeline.init(args)
        self.assertEqual(installed, ['text', 'math'])
        loaded = Project(destination).load()
        self.assertEqual({style['fontFamily'] for style in loaded['deck']['theme']['textStyles'].values()}, {'Portable Test'})
        config = json.loads((destination/'fonts.json').read_text())
        for path in [*config['families']['Portable Test'].values(), config['math']['regular']]:
            self.assertFalse(Path(path).is_absolute())
            self.assertTrue((destination/path).is_file())
        self.assertEqual(loaded['deck']['customFonts'][-1]['role'], 'math')

    def test_http_font_import_requires_auth_and_serves_declared_bytes_only(self):
        server, url = create_server(self.project)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        parsed = urlsplit(url)
        def request(method, path, body=None, auth=True):
            headers = {'Authorization': 'Bearer ' + parsed.fragment} if auth else {}
            if body is not None:headers['Content-Type'] = 'application/json'
            connection = HTTPConnection('127.0.0.1', parsed.port, timeout=10)
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            result = response.status, response.read(), dict(response.getheaders())
            connection.close()
            return result
        try:
            self.assertEqual(request('GET', '/api/font-catalog', auth=False)[0], 403)
            self.assertEqual(len(json.loads(request('GET', '/api/font-catalog')[1])['families']), 16)
            raw = test_font()
            body = dict(data=base64.b64encode(raw).decode(), manifestHash=self.project.load()['manifestHash'])
            self.assertEqual(request('POST', '/api/import-font', body, auth=False)[0], 403)
            code, data, _ = request('POST', '/api/import-font', body)
            self.assertEqual(code, 200)
            path = json.loads(data)['customFonts'][0]['src']
            self.assertEqual(request('GET', '/api/font?path=' + path, auth=False)[0], 403)
            code, data, headers = request('GET', '/api/font?path=' + path)
            self.assertEqual((code, data, headers['Content-Type']), (200, raw, 'font/ttf'))
            (self.root/'undeclared.ttf').write_bytes(raw)
            self.assertEqual(request('GET', '/api/font?path=undeclared.ttf')[0], 400)
            self.assertEqual(request('GET', '/api/font?path=../secret.ttf')[0], 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':unittest.main()
