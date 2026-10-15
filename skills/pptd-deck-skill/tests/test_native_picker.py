"""Platform commands and cancellation; no real system dialog in CI."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/local-export'))
import native_picker


class NativePickerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def test_commands_pass_paths_as_data_and_return_selected_directory(self):
        for platform in ('darwin', 'win32', 'linux'):
            response = subprocess.CompletedProcess([], 0, str(self.folder) + '\n', '')
            with self.subTest(platform=platform), patch.object(native_picker.sys, 'platform', platform), \
                    patch.dict(native_picker.os.environ, DISPLAY=':1'), \
                    patch.object(native_picker.shutil, 'which', return_value='/usr/bin/zenity'), \
                    patch.object(native_picker.subprocess, 'run', return_value=response) as run:
                prompt = 'title " $(private) `code`'
                self.assertEqual(native_picker.pick_folder(prompt, self.folder), self.folder.resolve())
                args, options = run.call_args
                self.assertIsInstance(args[0], list)
                self.assertNotIn('shell', options)
                self.assertEqual(options['env']['PPTD_PICKER_PROMPT'], prompt)
                if platform == 'darwin':
                    self.assertEqual(args[0][-2:], [prompt, str(self.folder)])
                    self.assertNotIn(prompt, args[0][2])

    def test_cancel_timeout_invalid_path_and_missing_desktop(self):
        with patch.object(native_picker.sys, 'platform', 'darwin'):
            with patch.object(native_picker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
                self.assertIsNone(native_picker.pick_folder('choose'))
            with patch.object(native_picker.subprocess, 'run', side_effect=subprocess.TimeoutExpired('picker', 300)):
                with self.assertRaisesRegex(ValueError, '超时'):native_picker.pick_folder('choose')
            with patch.object(native_picker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'relative/path', '')):
                with self.assertRaisesRegex(ValueError, '有效'):native_picker.pick_folder('choose')
        with patch.object(native_picker.sys, 'platform', 'linux'), patch.dict(native_picker.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, '桌面'):native_picker.pick_folder('choose')


if __name__ == '__main__':unittest.main()
