"""User-triggered system folder dialogs for the loopback editor.

Only fixed platform commands are executed. Paths/prompts are data, never shell
source. No browser upload is presented as permission to overwrite an original.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def pick_folder(prompt, initial=None):
    """Return a selected existing directory, or None when the user cancels."""
    initial = str(initial) if initial and Path(initial).is_dir() else ''
    environment = dict(os.environ, PPTD_PICKER_PROMPT=prompt, PPTD_PICKER_INITIAL=initial)
    if sys.platform == 'darwin':
        script = '''on run argv
set previousApp to path to frontmost application
try
  set promptText to item 1 of argv
  set initialPath to item 2 of argv
  tell application "Finder"
    activate
    if initialPath is "" then
      set selectedFolder to choose folder with prompt promptText
    else
      set selectedFolder to choose folder with prompt promptText default location (POSIX file initialPath)
    end if
  end tell
  tell application previousApp to activate
  return POSIX path of selectedFolder
on error number -128
  tell application previousApp to activate
  return ""
end try
end run'''
        command = ['/usr/bin/osascript', '-e', script, prompt, initial]
    elif sys.platform == 'win32':
        script = '''[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:PPTD_PICKER_PROMPT
$dialog.SelectedPath = $env:PPTD_PICKER_INITIAL
$dialog.ShowNewFolderButton = $true
try {
  if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Write($dialog.SelectedPath)
  }
} finally { $dialog.Dispose() }'''
        command = ['powershell.exe', '-NoProfile', '-STA', '-Command', script]
    elif os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
        if shutil.which('zenity'):
            command = ['zenity', '--file-selection', '--directory', '--title=' + prompt]
            if initial:
                command.append('--filename=' + initial.rstrip('/') + '/')
        elif shutil.which('kdialog'):
            command = ['kdialog', '--getexistingdirectory', initial or str(Path.home()), '--title', prompt]
        else:
            raise ValueError('系统文件夹选择器不可用。请安装 zenity 或 kdialog 后重试。')
    else:
        raise ValueError('系统文件夹选择器需要本地桌面会话。可使用“导入临时副本”上传文件夹。')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                env=environment, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('文件夹选择已超时，请重试。') from exc
    except OSError as exc:
        raise ValueError('无法打开系统文件夹选择器。') from exc
    if result.returncode in (1, 130) and sys.platform not in ('darwin', 'win32') and not result.stderr.strip():
        return None
    if result.returncode:
        raise ValueError('系统文件夹选择器失败：' + result.stderr.strip()[:300])
    path = result.stdout.rstrip('\r\n')
    if not path:
        return None
    folder = Path(path)
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError('选择器未返回有效文件夹。')
    return folder.resolve()
