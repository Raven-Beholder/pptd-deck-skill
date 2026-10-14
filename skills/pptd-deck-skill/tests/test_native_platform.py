"""Platform-specific command quoting and source distribution boundaries."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS));sys.path.insert(0,str(SCRIPTS.parents[2]/'tools'))
import pipeline
from audit_native_tree import audit
class NativePlatformTests(unittest.TestCase):
    def test_windows_editor_notice_is_powershell_safe_for_spaces_and_apostrophes(self):
        path=Path(tempfile.gettempdir())/"name's 中文 project"/'deck.pptd'
        with patch.object(pipeline.sys,'platform','win32'),patch.object(pipeline.sys,'executable',r'C:\Program Files\Python\python.exe'):
            command=pipeline.editor_command(path)
        self.assertTrue(command.startswith("& 'C:\\Program Files\\Python\\python.exe'"))
        self.assertIn("name''s 中文 project",command)
    def test_audit_rejects_binary_runtime_and_extracted_icon_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'native.py').write_text('print("own source")')
            self.assertTrue(audit(root)['currentTreeNativeOnly'])
            for name in ['old.wasm','font.woff2','reference-icons.mjs']:
                path=root/name;path.write_bytes(b'inert fixture')
                with self.subTest(name=name),self.assertRaises(ValueError):audit(root)
                path.unlink()
