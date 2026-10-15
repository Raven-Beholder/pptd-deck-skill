"""Native-only packaging, isolated execution and atomic publication regressions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'skills/pptd-deck-skill/scripts/local-export'))
from build_native_distribution import EDITOR_ASSETS, EDITOR_MODULES, MODULES, SOURCE, build, source_payload
import native_cli
from pptx_semantics import snapshot


class NativeDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-only-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = ROOT / 'skills/pptd-deck-skill/tests/fixtures/native'

    def test_archive_is_deterministic_and_runs_without_legacy_runtime(self):
        artifact = self.root / 'review.zip'
        first = build(artifact)
        self.assertEqual(first, build(artifact))
        runtime = self.root / 'runtime'
        with zipfile.ZipFile(artifact) as archive:
            self.assertEqual(set(archive.namelist()), {m + '.py' for m in MODULES} |
                             {'README.md', 'requirements.txt', 'NATIVE_NOTICE.md', 'MANIFEST.json'})
            manifest = json.loads(archive.read('MANIFEST.json'))
            for name, metadata in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), metadata['sha256'])
            self.assertFalse(manifest['certifiedCleanRoom'])
            self.assertFalse(manifest['fullReplacementAccepted'])
            archive.extractall(runtime)
        project = self.root / 'project'
        shutil.copytree(self.fixture, project)
        output = self.root / 'isolated.pptx'
        env = dict(os.environ, PATH=str(self.root / 'no-external-tools'), PYTHONPATH='')
        process = subprocess.run([sys.executable, str(runtime / 'native_cli.py'), str(project),
                                  '--output', str(output)], cwd=self.root, env=env,
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(json.loads(process.stdout)['legacyFallback'])
        self.assertEqual(len(snapshot(output)['slides']), 2)

    def test_dependency_gate_rejects_new_process_dependency_and_ignores_unlisted_assets(self):
        source = self.root / 'source'
        shutil.copytree(SOURCE, source)
        (source / 'vendor.wasm').write_bytes(b'not part of distribution')
        self.assertNotIn('vendor.wasm', source_payload(source))
        entry = source / 'native_cli.py'
        entry.write_text(entry.read_text() + '\nimport subprocess\n')
        with self.assertRaisesRegex(ValueError, 'unreviewed dependency'):
            source_payload(source)

    def test_editor_archive_includes_audited_frontend_and_can_start_isolated(self):
        artifact = self.root / 'editor-review.zip'
        first = build(artifact, editor=True)
        self.assertEqual(first, build(artifact, editor=True))
        runtime = self.root / 'editor-runtime'
        with zipfile.ZipFile(artifact) as archive:
            expected = {m + '.py' for m in MODULES + EDITOR_MODULES} | {
                'README.md', 'requirements.txt', 'NATIVE_NOTICE.md', 'ICONS_NOTICE.md', 'MANIFEST.json', 'font-catalog.json'} | {
                'native_editor/' + name for name in EDITOR_ASSETS}
            self.assertEqual(set(archive.namelist()), expected)
            manifest = json.loads(archive.read('MANIFEST.json'))
            self.assertEqual(manifest['entryPoint'], 'native_editor.py')
            for name, metadata in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), metadata['sha256'])
            archive.extractall(runtime)
        env = dict(os.environ, PATH=str(self.root / 'no-external-tools'), PYTHONPATH='')
        script = ('from native_editor import create_server; from native_project import Project; '
                  's,u=create_server(Project(' + repr(str(self.fixture)) + ')); '
                  'assert u.startswith("http://127.0.0.1:"); s.server_close(); print("isolated editor starts")')
        result = subprocess.run([sys.executable, '-c', script], cwd=runtime, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_export_and_existing_output_are_preserved(self):
        output = self.root / 'existing.pptx'
        output.write_bytes(b'previous output')
        with self.assertRaisesRegex(ValueError, 'output exists'):
            native_cli.export(self.fixture, output)
        project = self.root / 'bad'
        project.mkdir()
        (project / 'deck.pptd').write_text('version: v2\nsize: [960, 540]\npages: [one.page]\n')
        (project / 'one.page').write_text('elements: [{elementType: chart, elementId: c, bounds: [0,0,100,100]}]\n')
        with self.assertRaises(ValueError):
            native_cli.export(project, output, force=True)
        self.assertEqual(output.read_bytes(), b'previous output')
        native_cli.export(self.fixture, output, force=True)
        self.assertEqual(len(snapshot(output)['slides']), 2)

    def test_original_icons_have_no_vendor_asset_declaration(self):
        native = source_payload()
        editor = source_payload(editor=True)
        self.assertNotIn('native_editor/icons.mjs', native)
        self.assertEqual(json.loads(native['MANIFEST.json'])['thirdPartyAssets'], [])
        self.assertEqual(json.loads(editor['MANIFEST.json'])['thirdPartyAssets'], [])
        self.assertIn('native_editor/icons.mjs', editor)
        self.assertIn('ICONS_NOTICE.md', editor)
        self.assertNotIn(b'copied Kimi SVG', editor['README.md'])

    def test_no_force_race_does_not_clobber_concurrent_target(self):
        output = self.root / 'raced.pptx'
        def concurrent_create(source, target):
            Path(target).write_bytes(b'concurrent output')
            raise FileExistsError(target)
        with patch.object(native_cli.os, 'link', side_effect=concurrent_create):
            with self.assertRaises(FileExistsError):
                native_cli.export(self.fixture, output)
        self.assertEqual(output.read_bytes(), b'concurrent output')
        self.assertEqual(list(self.root.glob('.native-pptd-*')), [])


if __name__ == '__main__':
    unittest.main()
