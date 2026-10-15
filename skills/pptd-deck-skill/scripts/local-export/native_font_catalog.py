"""Explicitly requested, pinned OFL font downloads from official repositories.

Catalog entries record exact hashes, immutable source commits/releases and full
license notices. Fonts are installed into the selected project, never the OS or
the repository distribution. No document text or private path is transmitted.
"""
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

from native_project_fonts import font_info, require_editable, FONT_LIMIT

CATALOG = Path(__file__).with_name('font-catalog.json')


def catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def public_catalog():
    return [dict(id=item['id'], label=item['label'], family=item['family'], license=item['license'],
                 role=item.get('role', 'text'),
                 source=item['source'], faces=len(item['fonts']),
                 bytes=sum(font.get('fontBytes', font['bytes']) for font in item['fonts']))
            for item in catalog()]


def download_resource(resource, cache):
    url = resource['url']
    if url not in cache:
        if not url.startswith(('https://raw.githubusercontent.com/', 'https://github.com/')):
            raise ValueError('font source must be an allowlisted official repository')
        length = resource['bytes']
        if not isinstance(length, int) or not 0 < length <= 48 * 1024 * 1024:
            raise ValueError('font download exceeds resource limit')
        request = Request(url, headers={'User-Agent': 'PPTD-Project-Fonts/1.0'})
        try:
            with urlopen(request, timeout=45) as response:
                data = response.read(length + 1)
        except OSError as exc:
            raise ValueError('字体下载失败，请检查网络后重试。也可添加已下载的字体文件。') from exc
        if len(data) != length or hashlib.sha256(data).hexdigest() != resource['sha256']:
            raise ValueError('字体资源校验失败，未写入项目。')
        cache[url] = data
    data = cache[url]
    if len(data) != resource['bytes'] or hashlib.sha256(data).hexdigest() != resource['sha256']:
        raise ValueError('font resource cache/metadata mismatch')
    if resource.get('member'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            member = archive.getinfo(resource['member'])
            if member.file_size > FONT_LIMIT:
                raise ValueError('font archive member exceeds size limit')
            data = archive.read(member)
        if hashlib.sha256(data).hexdigest() != resource['memberSha256']:
            raise ValueError('字体文件校验失败，未写入项目。')
    return data


def install_family(project, identifier, manifest_hash):
    entry = next((item for item in catalog() if item['id'] == identifier), None)
    if entry is None:
        raise ValueError('unknown recommended font family')
    project.current(manifest_hash)
    cache = {}
    notice = download_resource(entry['notice'], cache).decode('utf-8')
    fonts = [download_resource(resource, cache) for resource in entry['fonts']]
    for data in fonts:
        info = font_info(data)
        require_editable(info)
        if entry['family'] not in info['aliases']:
            raise ValueError('recommended font family/resource mismatch')
    return project.import_font_bundle(fonts, manifest_hash, notice=notice, notice_name=entry['id'], role=entry.get('role', 'text'))


def project_font_config(project):
    """Relative font mappings usable by the native generation/QA pipeline."""
    from native_project_fonts import project_fonts
    resources = project_fonts(project.root, project.load()['deck'].get('customFonts'))
    families = {}
    math = None
    for resource in resources:
        if resource.role == 'math':
            if resource.variant == 'regular':
                math = {'regular': resource.src, 'syntheticStyles': True}
        else:
            families.setdefault(resource.family, {})[resource.variant] = resource.src
    return dict(families=families, **({'math': math} if math else {}))


def main():
    import argparse
    from native_common import configure_utf8_console
    from native_project import Project
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='list recommended redistributable OFL fonts')
    add = commands.add_parser('add', help='add pinned fonts and their complete notices to a PPTD project')
    add.add_argument('project', type=Path)
    add.add_argument('--family', action='append', required=True, help='catalog id; may be repeated')
    add.add_argument('--write-config', action='store_true', help='write relative fonts.json mappings for project fonts')
    args = parser.parse_args()
    try:
        if args.command == 'list':
            result = {'families': public_catalog()}
        else:
            project = Project(args.project)
            if args.write_config and (project.root / 'fonts.json').exists():
                raise ValueError('fonts.json exists; preserve it and merge project font mappings manually')
            identifiers = list(dict.fromkeys(args.family))
            known = {entry['id'] for entry in catalog()}
            if any(identifier not in known for identifier in identifiers):
                raise ValueError('unknown recommended font family; use fonts list')
            for identifier in identifiers:
                install_family(project, identifier, project.load()['manifestHash'])
            if args.write_config:
                raw = json.dumps(project_font_config(project), ensure_ascii=False, indent=2) + '\n'
                target = project.root / 'fonts.json'
                if target.is_symlink():raise ValueError('font config cannot be a symlink')
                with target.open('x', encoding='utf-8') as stream:stream.write(raw)
            result = dict(project=str(project.root), fonts=project.load()['fonts'])
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, 'project-fonts: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':raise SystemExit(main())
