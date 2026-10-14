"""Standalone native-only entry point; see NATIVE_NOTICE.md for license status."""
import argparse
from native_common import configure_utf8_console
import json
import os
from pathlib import Path
import tempfile
import zipfile

import yaml

from native_common import NativeExportError
from native_writer import export_native


def export(project, output, transition='fade', force=False):
    """Stage beside the target, verify ZIP integrity, then publish atomically."""
    manifest = Path(project).resolve()
    if manifest.is_dir():
        manifests = sorted(manifest.glob('*.pptd'))
        if len(manifests) != 1:
            raise NativeExportError('project directory must contain exactly one .pptd manifest')
        manifest = manifests[0]
    if not manifest.is_file() or manifest.suffix != '.pptd':
        raise NativeExportError('input must be a .pptd manifest or project directory')
    target = Path(output).absolute()
    if target.suffix.lower() != '.pptx':
        raise NativeExportError('output must have a .pptx extension')
    if target.exists() and not force:
        raise NativeExportError('output exists; use --force to replace it')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-pptd-', dir=target.parent) as staging:
        staged = Path(staging) / 'deck.pptx'
        slides = export_native(manifest, staged, transition, yaml.safe_load)
        with zipfile.ZipFile(staged) as archive:
            if archive.testzip() is not None:
                raise NativeExportError('generated ZIP failed CRC validation')
        size = staged.stat().st_size
        if force:
            os.replace(staged, target)
        else:
            # A hard link is an atomic no-clobber publish on this filesystem.
            # Unlike exists()+replace(), it also protects a concurrently created target.
            os.link(staged, target)
    return dict(output=str(target), slides=slides, bytes=size, exporter='native-python-v1',
                compatibility='experimental-subset', fontMode='system', legacyFallback=False)


def main(argv=None):
    configure_utf8_console()
    parser = argparse.ArgumentParser(description='Source-only PPTD v2 to PPTX exporter (experimental subset).')
    parser.add_argument('project', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--transition', choices=('fade', 'none'), default='fade')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = export(args.project, args.output, args.transition, args.force)
    except (OSError, ValueError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'native-pptd: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
