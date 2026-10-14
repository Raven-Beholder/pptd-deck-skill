"""Independent loopback-only PPTD web editor. See NATIVE_NOTICE.md."""
import argparse
from native_common import configure_utf8_console
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

import yaml

from native_project import ConflictError, Project, TEXT_LIMIT, page_value, parse
from native_preview import preview
from native_fonts import installed_families
from native_workspace import import_folder, project_archive, save_export
from native_math import parse as parse_math
from native_animation import schedule
from dataclasses import asdict
import threading
import tempfile

ASSETS = Path(__file__).with_name('native_editor')
STATIC = {'/': ('index.html', 'text/html'), '/app.mjs': ('app.mjs', 'text/javascript'),
          '/model.mjs': ('model.mjs', 'text/javascript'), '/styles.css': ('styles.css', 'text/css'),
          '/charts.mjs': ('charts.mjs', 'text/javascript'),
          '/text-format.mjs': ('text-format.mjs', 'text/javascript'),
          '/shapes.mjs': ('shapes.mjs', 'text/javascript'),
          '/playback.mjs': ('playback.mjs', 'text/javascript'),
          '/images.mjs': ('images.mjs', 'text/javascript'),
          '/ui.mjs': ('ui.mjs', 'text/javascript'),
          '/icons.mjs': ('icons.mjs', 'text/javascript'),
          '/math.mjs': ('math.mjs', 'text/javascript')}


def create_server(project, port=0, *, imported=False):
    token = secrets.token_urlsafe(32)
    font_names = None
    project_id = secrets.token_hex(16)
    workspaces = []
    workspace_lock = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        # No URL/body logging, including the session capability.
        def log_message(self, *args):
            pass

        def reply(self, status, data, kind='application/json'):
            if isinstance(data, dict):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') else ''))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def route(self):
            nonlocal font_names, project, project_id, imported
            expected_host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected_host:
                self.reply(403, {'error': 'invalid local host'})
                return
            origin = self.headers.get('Origin')
            if origin is not None and origin != 'http://' + expected_host:
                self.reply(403, {'error': 'cross-origin requests are forbidden'})
                return
            url = urlsplit(self.path)
            if self.command == 'GET' and url.path in STATIC:
                name, kind = STATIC[url.path]
                self.reply(200, (ASSETS / name).read_bytes(), kind)
                return
            if not secrets.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + token).encode('ascii')):
                self.reply(403, {'error': '请使用启动命令输出的完整链接打开编辑器。'})
                return
            active = self.headers.get('X-PPTD-Project')
            if active is not None and active != project_id:
                raise ConflictError('本地服务已切换项目；请保留草稿后重新打开。')
            if self.command == 'GET' and url.path == '/api/project':
                self.reply(200, dict(project.load(), projectId=project_id, root=str(project.root), imported=imported))
            elif self.command == 'GET' and url.path == '/api/fonts':
                if font_names is None:
                    font_names = installed_families()
                self.reply(200, {'families': font_names})
            elif self.command == 'GET' and url.path == '/api/image':
                data, kind = project.image(parse_qs(url.query).get('path', [''])[0])
                self.reply(200, data, kind)
            elif self.command == 'POST':
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('expected application/json')
                length = int(self.headers.get('Content-Length', '0'))
                limit = (140 if url.path == '/api/open-project' else 28 if url.path == '/api/save-export' else 20) * TEXT_LIMIT
                if not 0 < length <= limit:
                    raise ValueError('request exceeds editor limit')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('expected a JSON object')
                if url.path == '/api/parse':
                    self.reply(200, {'page': page_value(parse(body.get('text')))})
                elif url.path == '/api/open-project':
                    if 'files' in body:
                        temporary, candidate = import_folder(body['files'])
                        workspaces.append(temporary)
                        imported = True
                    else:
                        path = body.get('path')
                        if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
                            raise ValueError('请输入本地项目文件夹或 .pptd 文件的绝对路径。')
                        candidate = Project(Path(path).expanduser())
                        imported = False
                    project = candidate
                    project_id = secrets.token_hex(16)
                    self.reply(200, dict(project.load(), projectId=project_id, root=str(project.root), imported=imported))
                elif url.path == '/api/formula':
                    source = body.get('source')
                    if not isinstance(source, str) or not source.strip():
                        raise ValueError('请输入 LaTeX 公式。')
                    self.reply(200, {'expression': asdict(parse_math(source).expression)})
                elif url.path == '/api/playback':
                    value = page_value(body.get('page'))
                    identifiers = {element['elementId']: element['elementId'] for element in value['elements']}
                    groups = schedule(value.get('animations', []), identifiers)
                    self.reply(200, {'groups': [dict(click=click, events=[asdict(event) for event in events]) for click, events in groups]})
                elif url.path == '/api/preview':
                    value = page_value(body.get('page'))
                    theme = body.get('theme', project.load()['deck'].get('theme', {}))
                    if not isinstance(theme, dict):
                        raise ValueError('theme must be a mapping')
                    self.reply(200, {'elements': preview(value, theme)})
                elif url.path == '/api/serialize':
                    value = page_value(body.get('page'))
                    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
                    page_value(parse(text))
                    self.reply(200, {'text': text})
                elif url.path == '/api/save':
                    self.reply(200, project.save(body.get('path'), body.get('text'), body.get('hash'), body.get('manifestHash')))
                elif url.path == '/api/arrange-pages':
                    if not isinstance(body.get('hashes'), dict):
                        raise ValueError('expected baseline page hashes')
                    self.reply(200, project.arrange_pages(body.get('pages'), body.get('manifestHash'), body['hashes']))
                elif url.path == '/api/save-theme':
                    self.reply(200, project.save_theme(body.get('theme'), body.get('manifestHash')))
                elif url.path == '/api/import-image':
                    self.reply(200, project.import_image(body.get('data')))
                elif url.path == '/api/save-export':
                    self.reply(200, save_export(body.get('data'), body.get('directory'), body.get('filename')))
                elif url.path == '/api/export':
                    if not isinstance(body.get('hashes'), dict):
                        raise ValueError('expected baseline page hashes')
                    data = project.export(body.get('drafts'), body.get('manifestHash'), body['hashes'], body.get('theme'), body.get('transition', 'fade'), body.get('embedFonts', False))
                    self.reply(200, data, 'application/vnd.openxmlformats-officedocument.presentationml.presentation')
                elif url.path == '/api/download-project':
                    data = project_archive(project, body.get('drafts'), body.get('manifestHash'), body.get('hashes'), body.get('theme'))
                    self.reply(200, data, 'application/zip')
                else:
                    self.reply(404, {'error': 'unknown endpoint'})
            else:
                self.reply(404, {'error': 'unknown endpoint'})

        def handle_request(self):
            self.connection.settimeout(15)
            try:
                with workspace_lock:
                    self.route()
            except ConflictError as exc:
                self.reply(409, {'error': str(exc)})
            except (ValueError, OSError, yaml.YAMLError, RecursionError) as exc:
                self.reply(400, {'error': str(exc)})

        do_GET = handle_request
        do_POST = handle_request

    class EditorServer(ThreadingHTTPServer):
        def server_bind(self):
            # The service is explicitly IPv4 loopback-only; reverse DNS adds no
            # identity information and can hang on offline or CI hosts.
            from socketserver import TCPServer
            TCPServer.server_bind(self)
            self.server_name = '127.0.0.1'
            self.server_port = self.server_address[1]
        def server_close(self):
            super().server_close()
            for workspace in workspaces:
                workspace.cleanup()

    server = EditorServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server, f'http://127.0.0.1:{server.server_port}/#{token}'


def main():
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, nargs='?', help='optional local PPTD path; omit to open a blank project')
    parser.add_argument('--port', type=int, default=55174)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be within 0–65535')
    try:
        temporary = None
        if args.project is None:
            temporary = tempfile.TemporaryDirectory(prefix='pptd-new-project-')
            root = Path(temporary.name)
            (root / 'deck.pptd').write_text('version: v2\ntitle: 未命名演示文稿\nsize: [960,540]\npages: [01.page]\n', encoding='utf-8')
            (root / '01.page').write_text('elements: []\n', encoding='utf-8')
            project = Project(root)
        else:
            project = Project(args.project)
        server, url = create_server(project, args.port, imported=temporary is not None)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        parser.exit(1, f'native-editor: {exc}\n')
    print(f'Independent PPTD editor (experimental subset)\n{url}\nProject: {project.root}\nCtrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if temporary is not None:
            temporary.cleanup()


if __name__ == '__main__':
    main()
