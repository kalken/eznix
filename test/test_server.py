#!/usr/bin/env python3
"""Start eznix on a throwaway flake and check what it answers. No browser, no dependencies:

    python3 test/test_server.py

It covers the server and the plugins' server halves. What happens in the page (the editor, the
terminal panel) is not covered and has to be looked at in a browser."""
import http.client
import http.cookiejar
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 9790
BASE = f'http://127.0.0.1:{PORT}'
failures = []


def check(what, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + what + (f'   {detail}' if detail and not ok else ''))
    if not ok:
        failures.append(what)


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path, data=None, method=None, headers={}):
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, path, data=None, method=None):
        status, body = self.request(path, data, method)
        return status, json.loads(body or b'null')

    def terminal(self, origin=None):
        """The status of a WebSocket handshake for the terminal, as a page at `origin` would
        send it with this browser's cookies. 101 is a connection."""
        headers = {'Connection': 'Upgrade', 'Upgrade': 'websocket', 'Sec-WebSocket-Version': '13',
                   'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==',
                   'Cookie': '; '.join(f'{c.name}={c.value}' for c in self.cookies)}
        if origin is not None:
            headers['Origin'] = origin
        conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
        try:
            conn.request('GET', '/terminal', headers=headers)
            return conn.getresponse().status
        finally:
            conn.close()


def start(tmp, *extra):
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'bin', 'eznix.py'), '--flake', f'{tmp}/flake',
                             '--state-dir', f'{tmp}/state', '--port', str(PORT), '--password', 'pw', *extra],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + '/login.html', timeout=1)
            return proc
        except urllib.error.HTTPError:
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    sys.exit('eznix did not start')


def login(browser, password='pw'):
    data = urllib.parse.urlencode({'username': os.environ.get('USER') or os.getlogin(), 'password': password}).encode()
    return browser.request('/login', data)[0]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(f'{tmp}/flake/eznix')
        os.makedirs(f'{tmp}/flake/.git')
        os.makedirs(f'{tmp}/plugins/hello')
        for path, text in {'flake/flake.nix': 'original', 'flake/README.md': '# Hi', 'flake/.git/config': 'secret',
                           'flake/eznix/a.json': '{"a": 1}',
                           'plugins/hello/plugin.json': '{"name": "hello", "scripts": ["hello.js"], "server": "hello.py"}',
                           'plugins/hello/hello.js': '// hello',
                           'plugins/hello/hello.py': 'def setup(api):\n    api.get("hi", lambda req: {"hi": req.user, "n": api.config.get("n")})\n',
                           'conf.toml': f'hosts = ["https://nix.example.org"]\nexclude = ["package.json", "vendor/"]\nplugins_dir = "{tmp}/plugins"\n[plugin.hello]\nn = 3\n[plugin.documents]\nenabled = false\n'}.items():
            with open(f'{tmp}/{path}', 'w') as f:
                f.write(text)

        proc = start(tmp, '--no-terminal')
        try:
            anon, b = Browser(), Browser()
            check('nothing without a login', anon.request('/api/v1/ping')[0] == 401
                  and anon.request('/api/v1/plugin/system/export')[0] == 401
                  and anon.request('/plugins/system/system.js')[0] == 401)
            check('a wrong password is refused', login(Browser(), 'nope') == 401)
            check('the right one logs in', login(b) == 200)

            status, page = b.request('/')
            page = page.decode()
            check('the page loads its plugins', all(f'plugins/{p}' in page for p in ('system/system.js', 'documents/documents.js')))
            check('no terminal panel without a terminal', 'terminal-panel/terminal.js' not in page)
            check('every setting in the page is filled in', '%%EZNIX' not in page)
            _, ping = b.json('/api/v1/ping')
            check('the page was built with the checksum the ping reports', f"'{ping['page']}'" in page)

            check('files are listed', b.json('/api/v1/files')[1]['files'] == ['a.json'])
            check('a file saves', b.request('/api/v1/file/save?file=a.json', b'{"a": 2}')[0] == 200
                  and json.load(open(f'{tmp}/flake/eznix/a.json')) == {'a': 2})
            check('and the earlier version is kept', len(b.json('/api/v1/backups?file=a.json')[1]['backups']) == 1)
            save = lambda origin: b.request('/api/v1/file/save?file=a.json', b'{"a": 2}', headers={'Origin': origin})[0]
            check('a save from the page itself is accepted', save(BASE) == 200)
            check('one from another page is not: another port of this host, another site, none',
                  [save(o) for o in (f'http://127.0.0.1:{PORT + 1}', 'http://127.0.0.1', 'https://evil.example', 'null')] == [403] * 4)

            check('documents: lists', b.json('/api/v1/plugin/documents/files')[1] == {'files': ['README.md']})
            check('documents: reads', b.json('/api/v1/plugin/documents/content?name=README.md')[1] == {'content': '# Hi'})
            check('documents: nothing outside the flake', b.request('/api/v1/plugin/documents/content?name=../conf.toml')[0] == 400)

            status, data = b.request('/api/v1/plugin/system/export')
            names = sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())
            check('system: export holds the flake, without dot-files', names == ['README.md', 'eznix/a.json', 'flake.nix'], names)
            open(f'{tmp}/flake/extra.nix', 'w').write('new')
            open(f'{tmp}/flake/flake.nix', 'w').write('changed')
            _, result = b.json('/api/v1/plugin/system/import', data, 'POST')
            check('system: import makes the tree match the zip', result.get('removed') == ['extra.nix']
                  and open(f'{tmp}/flake/flake.nix').read() == 'original' and os.path.exists(f'{tmp}/flake/.git/config'), result)
            _, backups = b.json('/api/v1/plugin/system/backups')
            check('system: and backed up what was there', len(backups['backups']) == 1)
            b.json('/api/v1/plugin/system/restore?name=' + backups['backups'][0]['name'], b'', 'POST')
            check('system: restore brings it back', open(f'{tmp}/flake/flake.nix').read() == 'changed'
                  and os.path.exists(f'{tmp}/flake/extra.nix'))
            # As on NixOS, where the service owns its *.json folder and the rest is root's.
            def zipped(files):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as zf:
                    for name, text in files.items():
                        zf.writestr(name, text)
                return buf.getvalue()
            now = {n: zipfile.ZipFile(io.BytesIO(b.request('/api/v1/plugin/system/export')[1])).read(n).decode()
                   for n in ('README.md', 'eznix/a.json', 'extra.nix', 'flake.nix')}
            os.chmod(f'{tmp}/flake/flake.nix', 0o444)
            before = len(b.json('/api/v1/plugin/system/backups')[1]['backups'])
            status, result = b.json('/api/v1/plugin/system/import', zipped({**now, 'flake.nix': 'other', 'eznix/a.json': '{"a": 9}'}), 'POST')
            check('system: an import that would change a file eznix may not write changes nothing, and says which',
                  status == 403 and 'flake.nix' in result.get('error', '') and json.load(open(f'{tmp}/flake/eznix/a.json')) == {'a': 2}
                  and len(b.json('/api/v1/plugin/system/backups')[1]['backups']) == before, result)
            status, result = b.json('/api/v1/plugin/system/import', zipped({**now, 'eznix/a.json': '{"a": 9}'}), 'POST')
            check('system: one that leaves that file as it is goes through',
                  status == 200 and result.get('written') == ['eznix/a.json'] and result.get('unchanged') == 3
                  and json.load(open(f'{tmp}/flake/eznix/a.json')) == {'a': 9}, result)
            os.chmod(f'{tmp}/flake/flake.nix', 0o644)
            check('system: bad input is refused', b.request('/api/v1/plugin/system/import', b'not a zip', 'POST')[0] == 400
                  and b.request('/api/v1/plugin/system/restore?name=../x', b'', 'POST')[0] == 400)

            check("a plugin's page files are served", b.request('/plugins/system/system.js')[0] == 200)
            check('its server code and files outside it are not', b.request('/plugins/system/system.py')[0] == 404
                  and b.request('/plugins/system/../../index.html')[0] == 404)
            first, kept = ping['page'], b
        finally:
            proc.terminate(); proc.wait()

        proc = start(tmp, '--no-terminal')
        try:
            status, ping = kept.json('/api/v1/ping')
            check('a restart logs nobody out', status == 200)
            check('a restart that changes nothing keeps the checksum', status == 200 and ping['page'] == first)
        finally:
            proc.terminate(); proc.wait()

        # Other JSON than configuration in the folder, which conf.toml excludes.
        os.makedirs(f'{tmp}/flake/eznix/vendor/deep')
        for name in ('package.json', 'vendor/deep/x.json', 'vendored.json'):
            open(f'{tmp}/flake/eznix/{name}', 'w').write('{}')
        proc = start(tmp, '--no-terminal', '--config', f'{tmp}/conf.toml')
        try:
            b = Browser()
            login(b)
            page = b.request('/')[1].decode()
            check('a changed configuration changes it', b.json('/api/v1/ping')[1]['page'] != first)
            check('your own plugin is loaded, with its settings', 'plugins/hello/hello.js' in page and '"hello": {"n": 3}' in page)
            check('and its server code answers', b.json('/api/v1/plugin/hello/hi')[1].get('n') == 3)
            check('a plugin switched off is gone', 'plugins/documents' not in page
                  and b.request('/api/v1/plugin/documents/files')[0] == 404)
            save = lambda origin: b.request('/api/v1/file/save?file=a.json', b'{"a": 2}', headers={'Origin': origin})[0]
            check('no file name is special: custom-options.json is a tab like any other',
                  b.request('/api/v1/file/save?file=custom-options.json', b'{"a": 3}')[0] == 200
                  and 'custom-options.json' in b.json('/api/v1/files')[1]['files'])
            os.remove(f'{tmp}/flake/eznix/custom-options.json')
            listed = b.json('/api/v1/files')[1]
            check('excluded paths are no tabs and no folders, and a name that only starts like one is kept',
                  listed['files'] == ['a.json', 'vendored.json'] and listed['folders'] == [], listed)
            check('and cannot be read or written through the editor',
                  b.request('/api/v1/file?file=package.json')[0] != 200
                  and b.request('/api/v1/file/save?file=vendor/deep/x.json', b'{"a": 2}')[0] == 400
                  and open(f'{tmp}/flake/eznix/vendor/deep/x.json').read() == '{}')
            check("behind a proxy, the page's address listed in hosts is accepted, and only that",
                  [save(o) for o in ('https://nix.example.org', 'http://nix.example.org', 'https://nix.example.org:8443')] == [200, 403, 403])
        finally:
            proc.terminate(); proc.wait()

        proc = start(tmp)       # with the terminal eznix starts itself
        try:
            b = Browser()
            login(b)
            time.sleep(1)
            page = b.request('/')[1].decode()
            ping = b.json('/api/v1/ping')[1]
            check('the terminal panel is loaded when there is a terminal', 'terminal-panel/terminal.js' in page
                  and b.request('/terminal-panel/terminal.js')[0] == 200)
            check('the terminal runs, and is the one the editor expects', ping['terminal_stale'] is False, ping)

            check('the terminal opens for the page itself, and for a script', [b.terminal(BASE), b.terminal()] == [101, 101])
            check('not for another page: another port of this host, another site, none',
                  [b.terminal(o) for o in (f'http://127.0.0.1:{PORT + 2}', 'https://evil.example', 'null')] == [403] * 3)
            check('nor without a login', Browser().terminal(BASE) == 401)

            # In place of the one eznix started: the same program on the same port and key,
            # started by hand. "Not stale" is also the answer when eznix can't tell, so the
            # check above proves little alone; these two tell the cases apart.
            def terminal_by_hand(folder):
                subprocess.run(['pkill', '-f', f'eznix-terminal.py --port {PORT + 1} '])
                time.sleep(0.5)
                t = subprocess.Popen([sys.executable, os.path.join(ROOT, 'bin', 'eznix-terminal.py'), '--port', str(PORT + 1),
                                      '--key-file', f'{tmp}/state/terminal.key', '--dir', folder],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1)
                return t
            other = terminal_by_hand(tmp)
            try:
                check('a terminal started another way than configured is reported as out of date',
                      b.json('/api/v1/ping')[1]['terminal_stale'] is True)
            finally:
                other.terminate(); other.wait()
            same = terminal_by_hand(f'{tmp}/flake')
            try:
                check('and one started the configured way is not', b.json('/api/v1/ping')[1]['terminal_stale'] is False)
            finally:
                same.terminate(); same.wait()
        finally:
            proc.terminate(); proc.wait()

    print(f'\n{len(failures)} failed' if failures else '\nall passed')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
