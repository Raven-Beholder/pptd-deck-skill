"""Platform commands and real AppleScript control flow, without system dialogs."""
from pathlib import Path
import re
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

    @unittest.skipUnless(sys.platform == 'darwin', 'requires the macOS AppleScript interpreter')
    def test_macos_front_application_target_is_text(self):
        # Reading the front application needs no activation or folder dialog.
        handlers = native_picker.MACOS_PICKER_SCRIPT.split('on run argv\n')[0]
        script = handlers + 'on run argv\nreturn class of my previousApplicationPath()\nend run'
        result = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True,
                                text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'text')

    @unittest.skipUnless(sys.platform == 'darwin', 'requires the macOS AppleScript interpreter')
    def test_macos_focus_failure_preserves_selection_cancel_and_real_picker_errors(self):
        # Execute the shipped control flow in osascript. Only the UI boundary
        # is replaced; an injected -1728 exercises the reported failure.
        script = re.sub(r'(?ms)^on previousApplicationPath\(\).*?^end previousApplicationPath$',
                        'on previousApplicationPath()\nreturn "Fixture Application"\nend previousApplicationPath',
                        native_picker.MACOS_PICKER_SCRIPT)
        script = script.replace('tell application previousAppPath to activate',
                                'error "Simulated focus failure" number -1728')
        outcomes = [
            ('return POSIX path of (POSIX file initialPath as alias)', self.folder.resolve(), None),
            ('error number -128', None, None),
            ('error "Simulated chooser permission error" number -1743', None, '-1743'),
        ]
        for body, expected, failure in outcomes:
            candidate = re.sub(r'(?ms)^on chooseFolder\(promptText, initialPath\).*?^end chooseFolder$',
                               'on chooseFolder(promptText, initialPath)\n' + body + '\nend chooseFolder', script)
            with self.subTest(body=body), patch.object(native_picker, 'MACOS_PICKER_SCRIPT', candidate):
                if failure:
                    with self.assertRaisesRegex(ValueError, failure):
                        native_picker.pick_folder('choose " $() `code` 中文', self.folder)
                else:
                    self.assertEqual(native_picker.pick_folder('choose " $() `code` 中文', self.folder), expected)


if __name__ == '__main__':unittest.main()
