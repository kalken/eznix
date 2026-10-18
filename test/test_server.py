#!/usr/bin/env python3
"""Start eznix on a throwaway flake and check what it answers. No browser, no dependencies:

    python3 test/test_server.py

It covers the server and the plugins' server halves. What happens in the page (the editor, the
terminal panel) is not covered and has to be looked at in a browser."""
import http.client
import http.cookiejar
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import threading
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


def login_cookie():
    """The Set-Cookie header a login answers with."""
    conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
    try:
        conn.request('POST', '/login', urllib.parse.urlencode({'username': os.environ.get('USER') or os.getlogin(), 'password': 'pw'}),
                     {'Content-Type': 'application/x-www-form-urlencoded'})
        return conn.getresponse().getheader('Set-Cookie') or ''
    finally:
        conn.close()


def terminal_history():
    """The terminal's own record of the screen, which a page that reconnects is sent: since
    2026-10 with the lines that scrolled off the top above it. No server needed for these."""
    spec = importlib.util.spec_from_file_location('term', os.path.join(ROOT, 'bin', 'eznix-terminal.py'))
    term = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(term)
    screen = term._VirtualScreen(5, 20)
    screen.feed(b'$ ')
    check('terminal: a screen nothing has scrolled off is sent as before, cursor placed by row',
          screen.snapshot() == b'$\x1b[0m\x1b[1;3H', screen.snapshot())
    for i in range(1, 13):
        screen.feed(f'\x1b[31mline {i}\x1b[0m\r\n'.encode())
    screen.feed(b'$ ')
    sent = screen.snapshot().decode()
    lines = [l for l in sent.split('\r\n') if 'line' in l]
    check('terminal: lines that scrolled off the top come back above the screen, oldest first, in colour',
          lines[0] == '$ \x1b[0;31mline 1\x1b[0m' and lines[1] == '\x1b[0;31mline 2\x1b[0m' and len(lines) == 12, lines)
    check('terminal: the cursor is then placed counted from the last line', sent.endswith('$\x1b[0m\x1b[3G'), sent[-20:])
    screen.feed(b'\x1b[?1049h')
    check('terminal: not while a full-screen program has the screen', 'line 1' not in screen.snapshot().decode())
    screen.feed(b'\x1b[?1049l')
    check('terminal: and again once it is gone', 'line 1\x1b' in screen.snapshot().decode())
    screen.feed(b'\x1b[H\x1b[2J\x1b[3J')
    check('terminal: `clear` empties the history too', screen.snapshot() == b'\x1b[0m\x1b[1;1H', screen.snapshot())
    for _ in range(term.SCROLLBACK_LINES + 50):
        screen.feed(b'x\r\n')
    check('terminal: the history is bounded', len(screen._scrollback) == term.SCROLLBACK_LINES)


def excludes():
    """What `exclude` leaves out, entry by entry as in a .gitignore: the cases of
    test/exclude.json, which checks.exclude in flake.nix runs through nix/exclude.nix as well.
    The two read the entries separately and have to come to the same answers."""
    spec = importlib.util.spec_from_file_location('eznix_server', os.path.join(ROOT, 'bin', 'eznix.py'))
    ez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ez)
    wrong = []
    cases = json.load(open(os.path.join(ROOT, 'test', 'exclude.json')))
    for case in cases:
        ez.EXCLUDE = [r for r in map(ez._exclude_rule, case['exclude']) if r]
        if ez._excluded(case['path']) != case['out']:
            wrong.append(case)
    check(f'exclude: {len(cases)} cases of entries read as in a .gitignore', not wrong, wrong)


def sessions():
    """How long a login lasts, which is the server's doing and not the cookie's. No server
    needed: the clock is moved by rewriting what the functions go by."""
    spec = importlib.util.spec_from_file_location('eznix_server', os.path.join(ROOT, 'bin', 'eznix.py'))
    ez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ez)
    cookie = lambda token: {'Cookie': 'eznix_session=' + token}
    key = lambda token: ez._token_id(token)

    token = ez._new_session('alice')
    check('session: a login is one', ez._session(cookie(token))['user'] == 'alice')
    ez._SESSION_SEEN[key(token)] -= ez.SESSION_IDLE - 60
    check('session: and still one a little short of the idle time', ez._session(cookie(token)) is not None)
    ez._SESSION_SEEN[key(token)] -= ez.SESSION_IDLE + 1
    check('session: by default it ends once the page has not been heard from for 15 minutes',
          ez.SESSION_IDLE == 900 and ez._session(cookie(token)) is None and key(token) not in ez._SESSIONS)

    token = ez._new_session('alice')
    ez._SESSIONS[key(token)]['expires'] -= ez.SESSION_LIFETIME + 1
    check('session: and a day after the login, heard from or not',
          ez.SESSION_LIFETIME == 86400 and ez._session(cookie(token)) is None)
    check('session: its cookie has no lifetime of its own', 'Max-Age' not in ez._session_cookie(token))

    ez.SESSION_IDLE, ez.SESSION_LIFETIME = None, 30 * 86400      # what `days = 30` sets
    token = ez._new_session('alice')
    ez._SESSION_SEEN[key(token)] -= 20 * 86400
    check('session: with days set, a page closed for weeks is still logged in', ez._session(cookie(token)) is not None)
    ez._SESSIONS[key(token)]['expires'] -= 30 * 86400 + 1
    check('session: until the days are over', ez._session(cookie(token)) is None)


def login_limit():
    """The limit on tries at a login: counted before the password is checked, so tries sent at
    once cannot all get past it, and per client address, which behind a proxy is the one in
    X-Forwarded-For and only from a proxy that is trusted. No server needed."""
    spec = importlib.util.spec_from_file_location('eznix_login', os.path.join(ROOT, 'bin', 'eznix.py'))
    ez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ez)

    passed, lock = [], threading.Lock()
    def one():
        if not ez._login_begin('203.0.113.9')[0]:
            with lock:
                passed.append(1)
    threads = [threading.Thread(target=one) for _ in range(100)]
    for t in threads: t.start()
    for t in threads: t.join()
    check('login limit: 100 tries at once, only the first 5 get to the password',
          len(passed) == ez.LOGIN_MAX_ATTEMPTS, len(passed))
    check('login limit: and the rest are told how long to wait', 0 < ez._login_begin('203.0.113.9')[0] <= ez.LOGIN_WINDOW_SECONDS)
    check('login limit: another address is not affected', ez._login_begin('203.0.113.10')[0] == 0)
    ez._clear_login_failures('203.0.113.9')
    check('login limit: a login that works forgets the count', ez._login_begin('203.0.113.9')[0] == 0)

    check('login limit: the wait is told in minutes and seconds',
          [ez._minutes_seconds(n) for n in (1, 45, 60, 90, 120, 272, 300)] == ['1s', '45s', '1m', '1m 30s', '2m', '4m 32s', '5m'])

    xff = lambda v: {'X-Forwarded-For': v}
    check('client address: the connection itself, with no proxy listed',
          ez._client_ip('10.0.0.5', xff('198.51.100.7')) == '10.0.0.5')
    ez.TRUSTED_PROXIES = {'10.0.0.5', '10.0.0.6'}
    check('client address: from a listed proxy, the one it says', ez._client_ip('10.0.0.5', xff('198.51.100.7')) == '198.51.100.7')
    check('client address: not a claim written to the left of what the proxy added',
          ez._client_ip('10.0.0.5', xff('1.2.3.4, 198.51.100.7')) == '198.51.100.7')
    check('client address: proxies after each other are skipped',
          ez._client_ip('10.0.0.5', xff('198.51.100.7, 10.0.0.6')) == '198.51.100.7')
    check('client address: an entry that is no address is not believed',
          ez._client_ip('10.0.0.5', xff('198.51.100.7, not-an-address')) == '10.0.0.5')
    check('client address: nothing said, the proxy itself', ez._client_ip('10.0.0.5', {}) == '10.0.0.5')
    check('client address: from a connection that is not a listed proxy, the header is ignored',
          ez._client_ip('192.0.2.1', xff('198.51.100.7')) == '192.0.2.1')


def generator_plugins():
    """What the generator takes from plugins: which it finds, what it leaves out, and what one
    does for a kind of configuration it is not for. No nix needed."""
    spec = importlib.util.spec_from_file_location('eznix_autocomplete', os.path.join(ROOT, 'bin', 'eznix-autocomplete.py'))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    shipped = gen.find_plugins(None, [os.path.join(ROOT, 'plugins')])
    check('generator: the kernels, Homebrew and home-manager are plugins',
          {'kernels', 'homebrew', 'home-manager'} <= set(shipped), sorted(shipped))
    check('generator: and say what they are for',
          shipped['kernels']['module'].SYSTEMS == ('nixos',) and shipped['homebrew']['module'].SYSTEMS == ('darwin',)
          and set(shipped['home-manager']['module'].SYSTEMS) == {'nixos', 'darwin'}
          and shipped['home-manager']['module'].OPTIONS is True)
    with tempfile.TemporaryDirectory() as tmp:
        def plugin(name, code, manifest=None):
            os.makedirs(f'{tmp}/plugins/{name}')
            with open(f'{tmp}/plugins/{name}/plugin.json', 'w') as f:
                json.dump({'name': name, 'autocomplete': 'a.py', **(manifest or {})}, f)
            with open(f'{tmp}/plugins/{name}/a.py', 'w') as f:
                f.write(code)
        plugin('mine', 'def generate(ctx):\n    return {"choices": {"x.y": {"values": [ctx.kind, ctx.config["n"]]}}}\n')
        plugin('only-mac', 'SYSTEMS = ("darwin",)\ndef generate(ctx):\n    return {"choices": {}}\n')
        plugin('off', 'def generate(ctx):\n    return {}\n')
        plugin('broken', 'def generate(ctx) return\n')
        plugin('no-hook', 'x = 1\n')
        plugin('kernels', 'def generate(ctx):\n    return {"choices": {"mine": 1}}\n')   # named like a shipped one
        plugin('none', 'def generate(ctx):\n    return None\n', {'autocomplete': None})
        with open(f'{tmp}/eznix.toml', 'w') as f:
            f.write(f'plugins_dir = "{tmp}/plugins"\n[plugin.mine]\nn = "three"\n[plugin.off]\nenabled = false\n'
                    '[plugin.home-manager]\nenabled = false\n')
        found = gen.find_plugins(f'{tmp}/eznix.toml', [os.path.join(ROOT, 'plugins')])
        check('generator: a plugin of your own (plugins_dir) is found, with its settings',
              'mine' in found and found['mine']['config'] == {'n': 'three'})
        check('generator: enabled = false leaves one out, a shipped one too',
              'off' not in found and 'home-manager' not in found and 'kernels' in found)
        check('generator: one that does not load, has no generate() or no autocomplete file is left out',
              not {'broken', 'no-hook', 'none'} & set(found))
        check('generator: a folder named like a shipped plugin does not replace it',
              found['kernels']['module'].SYSTEMS == ('nixos',))
        gen.CONFIG_ATTR = 'darwinConfigurations'
        ctx_args = ('/flake', 'host', 'path:/flake#x')
        check('generator: a plugin is given what kind of configuration it runs for and its settings',
              gen.run_plugin('mine', found['mine'], ctx_args) == {'choices': {'x.y': {'values': ['darwin', 'three']}}})
        gen.CONFIG_ATTR = 'nixosConfigurations'
        check('generator: one for another kind is not run',
              gen.run_plugin('only-mac', {'module': importlib.import_module('types').SimpleNamespace(
                  SYSTEMS=('darwin',), generate=lambda ctx: {'choices': {'a': 1}}), 'config': {}}, ctx_args) is None)


def private_keys():
    """The certificate authority's key and the server's are for this user alone, under the
    NixOS service's umask (0002, which shares its other files with the group) as under a
    private one, and a key made before they were closed is closed by the next start. Needs the
    cryptography package, as the generator does; without it nothing is checked."""
    import stat
    spec = importlib.util.spec_from_file_location('eznix_server', os.path.join(ROOT, 'bin', 'eznix.py'))
    ez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ez)
    if not ez._CRYPTO:
        print('  (private keys: cryptography is not installed, not checked)')
        return
    mode = lambda d, f: stat.S_IMODE(os.stat(os.path.join(d, f)).st_mode)
    was = os.umask(0o002)
    try:
        with tempfile.TemporaryDirectory() as d:
            ez.generate_local_ca(d)
            check('keys: under umask 0002 both private keys are 0600',
                  mode(d, 'ca-key.pem') == 0o600 and mode(d, 'localhost-key.pem') == 0o600,
                  {f: oct(mode(d, f)) for f in os.listdir(d)})
            check('keys: and the certificates are readable by all and writable by this user alone',
                  mode(d, 'ca.pem') == 0o644 and mode(d, 'localhost.pem') == 0o644,
                  {f: oct(mode(d, f)) for f in os.listdir(d)})
            for f in ('ca-key.pem', 'localhost-key.pem', 'ca.pem', 'localhost.pem'):
                os.chmod(os.path.join(d, f), 0o664)
            ez.generate_local_ca(d)
            check('keys: ones made open by an earlier version are closed by the next start, certificates too',
                  mode(d, 'ca-key.pem') == 0o600 and mode(d, 'localhost-key.pem') == 0o600
                  and mode(d, 'ca.pem') == 0o644 and mode(d, 'localhost.pem') == 0o644)
            os.chmod(os.path.join(d, 'localhost-key.pem'), 0o664)
            ez.generate_local_ca(d, extra_sans=['another.example'])
            check('keys: and a server key made again for other names is closed',
                  mode(d, 'localhost-key.pem') == 0o600)
    finally:
        os.umask(was)


def backups_closed():
    """The backups of single files are eznix's alone to write, under the NixOS service's umask
    (0002) as under a private one, and a folder made open before is closed. No server needed."""
    import stat
    spec = importlib.util.spec_from_file_location('eznix_backups', os.path.join(ROOT, 'bin', 'eznix.py'))
    ez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ez)
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)
    was = os.umask(0o002)
    try:
        with tempfile.TemporaryDirectory() as d:
            ez.CONFIG_DIR, ez.BACKUP_DIR, ez.BACKUP_COUNT = f'{d}/conf', f'{d}/backups', 5
            os.makedirs(ez.CONFIG_DIR)
            with open(f'{d}/conf/a.json', 'w') as f:
                f.write('{}')
            os.chmod(f'{d}/conf/a.json', 0o664)
            ez.backup_config(f'{d}/conf/a.json')
            made = [f'{d}/backups/{n}' for n in os.listdir(f'{d}/backups')]
            check('backups: under umask 0002 the folder is 0755 and a backup 0644',
                  mode(f'{d}/backups') == 0o755 and made and all(mode(p) == 0o644 for p in made),
                  [oct(mode(f'{d}/backups'))] + [oct(mode(p)) for p in made])
            os.chmod(f'{d}/backups', 0o775)
            ez.backup_config(f'{d}/conf/a.json')
            check('backups: a folder made open before is closed by the next backup', mode(f'{d}/backups') == 0o755)
    finally:
        os.umask(was)


def origin_check():
    """Whether a request came from eznix's own page: its Origin names the address the request
    was sent to. '*' in hosts leaves the name open, not this. No server needed."""
    spec = importlib.util.spec_from_file_location('eznix_origin', os.path.join(ROOT, 'bin', 'eznix.py'))
    ez = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ez)
    req = lambda origin, host='10.0.0.7:9090': {'Host': host, **({'Origin': origin} if origin else {})}
    for hosts in (set(), {'*'}):
        ez.TRUSTED_HOSTS = hosts
        said = f'hosts = {sorted(hosts)}'
        check(f'origin ({said}): the page itself passes, by address or by name',
              ez._valid_origin(req('http://10.0.0.7:9090'))
              and ez._valid_origin(req('https://box.lan:9090', 'box.lan:9090')))
        check(f'origin ({said}): another port of the same host does not',
              not ez._valid_origin(req('http://10.0.0.7:8080')) and not ez._valid_origin(req('null')))
        check(f'origin ({said}): no Origin (curl, a script) passes', ez._valid_origin(req(None)))
    ez.TRUSTED_HOSTS = {'*', 'https://nix.example.org'}
    check("origin: behind a proxy that changes Host, the page's origin listed beside '*' passes",
          ez._valid_origin(req('https://nix.example.org', '127.0.0.1:9090')))


def main():
    terminal_history()
    backups_closed()
    origin_check()
    sessions()
    login_limit()
    generator_plugins()
    private_keys()
    excludes()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(f'{tmp}/flake/eznix')
        os.makedirs(f'{tmp}/flake/.git')
        os.makedirs(f'{tmp}/plugins/hello')
        for path, text in {'flake/flake.nix': 'original', 'flake/README.md': '# Hi', 'flake/.git/config': 'secret',
                           'flake/eznix/a.json': '{"a": 1}',
                           'plugins/hello/plugin.json': '{"name": "hello", "scripts": ["hello.js"], "server": "hello.py"}',
                           'plugins/hello/hello.js': '// hello',
                           'plugins/hello/hello.py': 'def setup(api):\n    api.get("hi", lambda req: {"hi": req.user, "n": api.config.get("n")})\n',
                           'conf.toml': f'interfaces = ["lo", "no-such-interface0"]\nlisten_addresses = ["127.0.0.1"]\ncollapse_level = 6\nindent = 1.5\narrow_level = 1\nhosts = ["https://nix.example.org"]\nexclude = ["package.json", "vendor/"]\nplugins_dir = "{tmp}/plugins"\n[session]\ndays = 0.5\n[plugin.hello]\nn = 3\n[plugin.documents]\nenabled = false\n[plugin.system]\nexclude = ["*.md", "/secret", "!keep.md", ".*", "!.shown"]\n[plugin.files]\nexclude = [".*", "sub"]\neditor = "hx"\n[[plugin.files.menus]]\nname = "Text"\nextensions = [".md", ".txt"]\ncommand = "nano -w"\n[[plugin.files.menus]]\nextensions = [".nix"]\n'}.items():
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
            cookie = login_cookie()
            check('with no days set, the login cookie has no lifetime of its own (the server ends the login)',
                  cookie.startswith('eznix_session=') and 'max-age' not in cookie.lower() and 'expires' not in cookie.lower(), cookie)

            status, page = b.request('/')
            page = page.decode()
            check('the page loads its plugins', all(f'plugins/{p}' in page for p in ('system/system.js', 'documents/documents.js')))
            check('no terminal panel without a terminal', 'terminal-panel/terminal.js' not in page)

            # Not framed by another site, and not sniffed: nosniff makes a browser refuse a script
            # or a stylesheet whose type is wrong, so the types of the page's own files are
            # checked with it.
            seen = {}
            for path in ('/', '/style.css', '/plugins/system/system.js', '/theme-nixos.css', '/manifest.json'):
                req = urllib.request.Request(BASE + path, headers={'Cookie': '; '.join(f'{c.name}={c.value}' for c in b.cookies)})
                with urllib.request.urlopen(req, timeout=10) as r:
                    seen[path] = (r.headers.get('X-Frame-Options'), r.headers.get('X-Content-Type-Options'),
                                  r.headers.get('Content-Type', '').split(';')[0])
            check('answers cannot be framed and are not sniffed',
                  all(v[0] == 'DENY' and v[1] == 'nosniff' for v in seen.values()), seen)
            # The page's own scripts and handlers are what its policy allows, found by reading the
            # page the way a browser does (html.parser), apart from the code that made the policy.
            import base64, hashlib, html.parser
            class Inline(html.parser.HTMLParser):
                def __init__(self):
                    super().__init__(); self.found = []; self.cur = None
                def handle_starttag(self, tag, attrs):
                    self.found += [v for k, v in attrs if k.startswith('on') and v is not None]
                    if tag == 'script' and not any(k == 'src' for k, _ in attrs):
                        self.cur = ''
                def handle_data(self, data):
                    if self.cur is not None:
                        self.cur += data
                def handle_endtag(self, tag):
                    if tag == 'script' and self.cur is not None:
                        self.found.append(self.cur); self.cur = None
            def allowed(text, policy):
                return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'" in policy
            req = urllib.request.Request(BASE + '/', headers={'Cookie': '; '.join(f'{c.name}={c.value}' for c in b.cookies)})
            with urllib.request.urlopen(req, timeout=10) as r:
                policy, body = r.headers.get('Content-Security-Policy', ''), r.read().decode()
            parsed_page = Inline(); parsed_page.feed(body)
            check('the page has a policy that allows its own scripts and handlers, and nothing inline besides',
                  parsed_page.found and all(allowed(x, policy) for x in parsed_page.found)
                  and "script-src 'self' 'unsafe-hashes' 'sha256-" in policy and "'unsafe-inline'" not in policy.split('style-src')[0]
                  and "object-src 'none'" in policy and "frame-ancestors 'none'" in policy, policy[:300])
            with urllib.request.urlopen(urllib.request.Request(BASE + '/', headers={'Accept': 'text/html'}), timeout=10) as r:
                login_policy, login_body = r.headers.get('Content-Security-Policy', ''), r.read().decode()
            parsed_login = Inline(); parsed_login.feed(login_body)
            check('the login page too',
                  'name="password"' in login_body and parsed_login.found
                  and all(allowed(x, login_policy) for x in parsed_login.found), login_policy[:200])
            check('and the page, its stylesheets and its scripts have the types nosniff needs',
                  seen['/'][2] == 'text/html' and seen['/style.css'][2] == 'text/css'
                  and seen['/theme-nixos.css'][2] == 'text/css'
                  and seen['/plugins/system/system.js'][2] in ('text/javascript', 'application/javascript'), seen)
            check('every setting in the page is filled in', '%%EZNIX' not in page)
            _, ping = b.json('/api/v1/ping')
            check('the page was built with the checksum the ping reports', f"'{ping['page']}'" in page)

            # The icon is public (the login page shows it) and drawn per theme.
            icon = lambda q='': anon.request('/favicon.svg' + q)[1].decode()
            check('the icon is the logo in a theme\'s two colours, with nothing behind it',
                  all(c in icon('?theme=nixos') for c in ('#5277c3', '#7ebae4'))
                  and '#0d1a2e' not in icon('?theme=nixos') and '<rect' not in icon('?theme=nixos')
                  and '#d65d0e' in icon('?theme=gruvbox') and 'var(' not in icon('?theme=osx-dark'))
            check('the filled icon has the header\'s fill behind the logo',
                  '#0d1a2e' in icon('?theme=nixos&filled=1') and '<rect' in icon('?theme=nixos&filled=1'))
            check('an unknown theme gets the configured one', icon('?theme=../x') == icon())
            manifest = json.loads(anon.request('/manifest.json')[1])
            check('the manifest names the icon with the configured theme',
                  manifest['icons'][0]['src'].startswith('favicon.svg?theme='), manifest)
            check('the manifest gives the window the theme\'s colours',
                  re.fullmatch(r'#[0-9a-fA-F]{6}', manifest.get('theme_color', ''))
                  and re.fullmatch(r'#[0-9a-fA-F]{6}', manifest.get('background_color', '')), manifest)
            check('the manifest\'s maskable icon is the filled one, its other the bare logo',
                  ['filled=1' in i['src'] for i in manifest['icons']] == [False, True]
                  and manifest['icons'][1]['purpose'] == 'maskable', manifest)

            # The page and its files are kept by the browser, which asks each time whether its
            # copy, named by the checksum it came with, is still the one.
            def fetch(path, etag=None):
                req = urllib.request.Request(BASE + path, headers={'If-None-Match': etag} if etag else {})
                try:
                    with b.opener.open(req, timeout=10) as r:
                        return r.status, r.headers, r.read()
                except urllib.error.HTTPError as e:
                    return e.code, e.headers, e.read()
            for path in ('/', '/style.css', '/plugins/system/system.js'):
                status, headers, body = fetch(path)
                etag = headers.get('ETag')
                check(f'{path} comes with a checksum and is to be asked about each time',
                      status == 200 and etag and body and headers.get('Cache-Control') == 'private, no-cache',
                      dict(headers))
                again = fetch(path, etag)
                check('and is not sent again to a browser that has it',
                      again[0] == 304 and not again[2] and again[1].get('ETag') == etag, again[0])
                check('but is to one that has another', fetch(path, '"0000000000000000"')[0] == 200)
            check('an answer of the API is still never kept',
                  fetch('/api/v1/files')[1].get('Cache-Control') == 'no-store')

            # A connection is used again after an answer that went well and says how long it is,
            # and closed after anything else.
            cookie = '; '.join(f'{c.name}={c.value}' for c in b.cookies)
            conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
            try:
                seen = []
                for path in ('/api/v1/ping', '/style.css', '/api/v1/files?content=1', '/'):
                    conn.request('GET', path, headers={'Cookie': cookie})
                    r = conn.getresponse(); r.read()
                    seen.append((r.status, r.getheader('Connection'), conn.sock is not None))
                check('one connection serves request after request', all(x == (200, None, True) for x in seen), seen)
                conn.request('POST', '/api/v1/file/backup?file=nope.json', b'', {'Cookie': cookie, 'Origin': BASE})
                r = conn.getresponse(); r.read()
                check('and is closed after a POST', r.getheader('Connection') == 'close', r.getheader('Connection'))
            finally:
                conn.close()
            conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
            try:
                conn.request('GET', '/api/v1/ping')
                r = conn.getresponse(); r.read()
                check('and after a refusal', r.status == 401 and r.getheader('Connection') == 'close', r.getheader('Connection'))
            finally:
                conn.close()

            check('files are listed', b.json('/api/v1/files')[1]['files'] == ['a.json'])
            whole = b.json('/api/v1/files?content=1')[1]
            check('and come with their text when asked, only then',
                  whole['content'] == {'a.json': open(f'{tmp}/flake/eznix/a.json').read()}
                  and 'content' not in b.json('/api/v1/files')[1], whole)
            check('a file saves', b.request('/api/v1/file/save?file=a.json', b'{"a": 2}')[0] == 200
                  and json.load(open(f'{tmp}/flake/eznix/a.json')) == {'a': 2})
            check('and the earlier version is kept', len(b.json('/api/v1/backups?file=a.json')[1]['backups']) == 1)
            kept = lambda: len(b.json('/api/v1/backups?file=a.json')[1]['backups'])
            check('a file is backed up on request too', b.json('/api/v1/file/backup?file=a.json', b'', 'POST')[0] == 200
                  and kept() == 2)
            check('one that is not on disk is not', b.json('/api/v1/file/backup?file=nope.json', b'', 'POST')[0] == 400
                  and kept() == 2)

            # Disabling is a rename on disk; the backups are the file's all the same.
            rename = lambda a, z: b.json('/api/v1/file/rename', json.dumps({'from': a, 'to': z}).encode(), 'POST')[0]
            check('a disabled file keeps its backups', rename('a.json', 'a.json.disabled') == 200
                  and len(b.json('/api/v1/backups?file=a.json.disabled')[1]['backups']) == 2)
            check('and has them still when enabled again', rename('a.json.disabled', 'a.json') == 200 and kept() == 2)

            # A folder is switched off by its name, which json2nix.nix leaves out ("X.disabled").
            os.makedirs(f'{tmp}/flake/eznix/web')
            with open(f'{tmp}/flake/eznix/web/w.json', 'w') as f:
                f.write('{}')
            folder = lambda what, name: b.json(f'/api/v1/folder/{what}', json.dumps({'folder': name}).encode(), 'POST')[0]
            listed = lambda: b.json('/api/v1/files')[1]
            check('a folder is disabled by renaming it, and its files are still listed',
                  folder('disable', 'web') == 200 and os.path.isdir(f'{tmp}/flake/eznix/web.disabled')
                  and 'web.disabled/w.json' in listed()['files'], listed())
            b.request('/api/v1/file/save?file=web.disabled/w.json', b'{"a": 1}')
            b.json('/api/v1/file/backup?file=web.disabled/w.json', b'', 'POST')
            in_folder = lambda name: len(b.json(f'/api/v1/backups?file={name}')[1]['backups'])
            check('a file backed up inside a disabled folder has its backups there', in_folder('web.disabled/w.json') >= 1)
            check('and enabled again', folder('enable', 'web.disabled') == 200
                  and 'web/w.json' in listed()['files'], listed())
            check('and the same ones once the folder is enabled', in_folder('web/w.json') >= 1)
            os.rename(f'{tmp}/flake/eznix/web', f'{tmp}/flake/eznix/.web.disabled')
            check('one disabled the old way, with a dot in front, is still listed and can be enabled',
                  '.web.disabled/w.json' in listed()['files'] and folder('enable', '.web.disabled') == 200
                  and 'web/w.json' in listed()['files'], listed())
            shutil.rmtree(f'{tmp}/flake/eznix/web')
            save = lambda origin: b.request('/api/v1/file/save?file=a.json', b'{"a": 2}', headers={'Origin': origin})[0]
            check('a save from the page itself is accepted', save(BASE) == 200)
            named = lambda host: b.request('/api/v1/file/save?file=a.json', b'{"a": 2}', headers={'Host': host, 'Origin': 'http://' + host})
            check('by any address in figures too, and not by a name eznix was not told of, which the answer says',
                  named('192.168.122.149:9690')[0] == 200 and named('[fe80::1]:9690')[0] == 200
                  and named('ezvm.local:9690')[0] == 403 and b'ezvm.local' in named('ezvm.local:9690')[1])
            check('one from another page is not: another port of this host, another site, none',
                  [save(o) for o in (f'http://127.0.0.1:{PORT + 1}', 'http://127.0.0.1', 'https://evil.example', 'null')] == [403] * 4)

            check('documents: lists', b.json('/api/v1/plugin/documents/files')[1] == {'files': ['README.md']})
            check('documents: reads', b.json('/api/v1/plugin/documents/content?name=README.md')[1] == {'content': '# Hi'})
            check('documents: nothing outside the flake', b.request('/api/v1/plugin/documents/content?name=../conf.toml')[0] == 400)

            check('no section is folded with nothing set', 'const SECTIONS_LEVEL    = 0;' in page, None)
            check('open sections have arrows from level 3 with nothing set', 'const ARROW_LEVEL       = 3;' in page, None)
            check('the indent is 2 with nothing set', '<style>html:root { --indent-step: 2ch; }</style>' in page, None)
            check('files: with nothing set, one menu of the Nix files, and listing is all it answers',
                  b.json('/api/v1/plugin/files/files')[1] == {'menus': [['flake.nix']], 'folders': ['eznix']}
                  and '"menus": [{"name": "Nix files", "extensions": [".nix"], "command": ""}]' in page
                  and b.request('/api/v1/plugin/files/content?name=flake.nix')[0] == 404)

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
            # What describes the machine stays the machine's through an import, not a restore.
            now['eznix/a.json'] = '{"a": 9}'       # as the import above left it
            with open(f'{tmp}/flake/hardware-configuration.nix', 'w') as f:
                f.write('this machine')
            status, result = b.json('/api/v1/plugin/system/import', zipped({**now, 'hardware-configuration.nix': 'another machine'}), 'POST')
            check("system: an import leaves this machine's hardware file as it is, and says so",
                  status == 200 and result.get('kept') == ['hardware-configuration.nix']
                  and open(f'{tmp}/flake/hardware-configuration.nix').read() == 'this machine', result)
            status, result = b.json('/api/v1/plugin/system/import', zipped(now), 'POST')
            check('system: nor is it removed by a zip that has none',
                  status == 200 and result.get('removed') == [] and os.path.exists(f'{tmp}/flake/hardware-configuration.nix'), result)
            os.remove(f'{tmp}/flake/hardware-configuration.nix')
            status, result = b.json('/api/v1/plugin/system/import', zipped({**now, 'hardware-configuration.nix': 'another machine'}), 'POST')
            check('system: a machine without one takes the zip\'s',
                  status == 200 and open(f'{tmp}/flake/hardware-configuration.nix').read() == 'another machine', result)
            os.remove(f'{tmp}/flake/hardware-configuration.nix')
            # A zip that is not a system at all would, taken for one, remove the whole flake.
            tree = lambda: sorted(os.path.relpath(os.path.join(d, f), f'{tmp}/flake') for d, _, fs in os.walk(f'{tmp}/flake') for f in fs)
            had, snapshots = tree(), len(b.json('/api/v1/plugin/system/backups')[1]['backups'])
            status, result = b.json('/api/v1/plugin/system/import', zipped({'a.json': '{}', 'notes/b.txt': 'x'}), 'POST')
            check('system: a zip without a flake.nix at its top is refused, nothing changed and no backup made',
                  status == 400 and 'not a system' in result.get('error', '') and tree() == had
                  and len(b.json('/api/v1/plugin/system/backups')[1]['backups']) == snapshots, result)
            status, result = b.json('/api/v1/plugin/system/import', zipped({'repo-main/' + n: t for n, t in now.items()}), 'POST')
            check('system: one with a folder around the flake too, and is told where its flake.nix is',
                  status == 400 and 'repo-main/' in result.get('error', '') and tree() == had, result)
            status, result = b.json('/api/v1/plugin/system/import', zipped({}), 'POST')
            check('system: and an empty one', status == 400 and tree() == had, result)
            # A zip made to write outside the flake: by "..", by a path from the root, by a
            # backslash, and through a link inside the flake that leads out of it.
            now['eznix/a.json'] = '{"a": 9}'
            out = f'{tmp}/outside'
            os.makedirs(out, exist_ok=True)
            hostile = {'../outside/up.txt': 'x', 'eznix/../../outside/up2.txt': 'x', f'{out}/abs.txt': 'x',
                       '..\\outside\\back.txt': 'x', '/outside-root.txt': 'x'}
            status, result = b.json('/api/v1/plugin/system/import', zipped({**now, **hostile}), 'POST')
            check('system: a zip with paths that lead out of the flake writes none of them',
                  status == 200 and os.listdir(out) == [] and not os.path.exists('/outside-root.txt')
                  and sorted(result.get('skipped', [])) == sorted(hostile) and result.get('written') == [], result)
            os.symlink(out, f'{tmp}/flake/way-out')
            status, result = b.json('/api/v1/plugin/system/import', zipped({**now, 'way-out/through-link.txt': 'x'}), 'POST')
            check('system: nor one that goes through a link in the flake to somewhere else, and it changes nothing',
                  status == 400 and os.listdir(out) == [] and os.path.exists(f'{tmp}/flake/extra.nix'), result)
            os.remove(f'{tmp}/flake/way-out')

            # A zip that claims more than a flake can hold: a file over 1 GiB (it packs to about
            # a megabyte) is refused before anything is touched, as is one with too many entries.
            big = io.BytesIO()
            with zipfile.ZipFile(big, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                zf.writestr('flake.nix', now['flake.nix'])
                with zf.open('huge.bin', 'w', force_zip64=True) as f:
                    chunk = bytes(1 << 20)
                    for _ in range(1025):
                        f.write(chunk)
            status, result = b.json('/api/v1/plugin/system/import', big.getvalue(), 'POST')
            check('system: a zip with a file over 1 GiB is refused, and changes nothing',
                  status == 413 and tree() == had and not os.path.exists(f'{tmp}/flake/huge.bin'), (status, result))
            many = io.BytesIO()
            with zipfile.ZipFile(many, 'w') as zf:
                zf.writestr('flake.nix', now['flake.nix'])
                for n in range(100_001):
                    zf.writestr(f'f/{n}', '')
            status, result = b.json('/api/v1/plugin/system/import', many.getvalue(), 'POST')
            check('system: and one with a hundred thousand entries', status == 413 and tree() == had, (status, result))

            # A body is as long as the request says and no longer than eznix will read. Raw, since
            # a client library would not send these.
            def raw(path, length, cookie=True):
                conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
                try:
                    headers = {'Content-Length': length, 'Origin': BASE, 'Content-Type': 'application/json'}
                    if cookie:
                        headers['Cookie'] = '; '.join(f'{c.name}={c.value}' for c in b.cookies)
                    conn.request('POST', path, headers=headers)
                    return conn.getresponse().status
                finally:
                    conn.close()
            check('a length that is not a number is refused, also before logging in',
                  raw('/login', '-1', cookie=False) == 400 and raw('/login', 'abc', cookie=False) == 400
                  and raw('/api/v1/file/save', '-5') == 400)
            check('the login takes 16 KiB, the API 64 MiB, a plugin 512 MiB',
                  raw('/login', str(16 * 1024 + 1), cookie=False) == 413
                  and raw('/api/v1/file/save', str(64 * 1024 * 1024 + 1)) == 413
                  and raw('/api/v1/plugin/system/import', str(512 * 1024 * 1024 + 1)) == 413)
            before = b.json('/api/v1/plugin/system/backups')[1]['backups']
            status, made = b.json('/api/v1/plugin/system/backup', b'', 'POST')
            after = b.json('/api/v1/plugin/system/backups')[1]['backups']
            check('system: a backup can be made on request, and is the newest in the list',
                  status == 200 and made.get('files') == 4 and after[0]['name'] == made.get('name')
                  and made['name'] not in [x['name'] for x in before], made)
            status, _ = b.json('/api/v1/plugin/system/delete?name=' + made['name'], b'', 'POST')
            check('system: a backup can be deleted, and only a backup',
                  status == 200 and made['name'] not in [x['name'] for x in b.json('/api/v1/plugin/system/backups')[1]['backups']]
                  and b.request('/api/v1/plugin/system/delete?name=../sessions.json', b'', 'POST')[0] == 400
                  and b.request('/api/v1/plugin/system/delete?name=sessions.json', b'', 'POST')[0] == 400
                  and os.path.exists(f'{tmp}/state/sessions.json'))
            check('system: bad input is refused', b.request('/api/v1/plugin/system/import', b'not a zip', 'POST')[0] == 400
                  and b.request('/api/v1/plugin/system/restore?name=../x', b'', 'POST')[0] == 400)

            check("a plugin's page files are served", b.request('/plugins/system/system.js')[0] == 200)
            check('its server code and files outside it are not', b.request('/plugins/system/system.py')[0] == 404
                  and b.request('/plugins/system/../../index.html')[0] == 404)
            check('nor in other letters, which a disk that does not tell them apart takes for the same file',
                  [b.request(p)[0] for p in ('/plugins/system/system.PY', '/plugins/system/PLUGIN.JSON', '/plugins/system/README.MD')] == [404] * 3)
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
            check('[session] days sets how long the login cookie lasts', 'Max-Age=43200;' in login_cookie() + ';', login_cookie())
            conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
            conn.request('GET', '/', headers={'Cookie': '; '.join(f'{c.name}={c.value}' for c in b.cookies)})
            resp = conn.getresponse(); resp.read(); conn.close()
            check('and opening the page does not start the count again', resp.status == 200 and not resp.getheader('Set-Cookie'), resp.getheader('Set-Cookie'))
            check('reached through lo, with an interface beside it that is not there, it still answers here', b.request('/api/v1/ping')[0] == 200)
            check('a changed configuration changes it', b.json('/api/v1/ping')[1]['page'] != first)
            check('collapse_level is the level they are folded from', 'const SECTIONS_LEVEL    = 6;' in page)
            check('arrow_level is the level open sections have arrows from', 'const ARROW_LEVEL       = 1;' in page)
            check('indent takes the place of the theme\'s', '<style>html:root { --indent-step: 1.5ch; }</style>' in page)
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
            os.makedirs(f'{tmp}/flake/secret'); os.makedirs(f'{tmp}/flake/sub/secret')
            made = ('notes.md', 'keep.md', 'sub/more.md', 'secret/key.nix', 'sub/secret/x.nix', '.hidden', '.shown')
            for name in made:
                open(f'{tmp}/flake/{name}', 'w').write('x')
            listed = b.json('/api/v1/plugin/files/files')[1]
            check('files: the menus that are set, each with its kinds of file and its command, less what is excluded',
                  listed['menus'] == [['README.md', 'keep.md', 'notes.md'], ['extra.nix', 'flake.nix', 'secret/key.nix']]
                  and 'secret' in listed['folders'] and 'sub' not in listed['folders']
                  and '"menus": [{"name": "Text", "extensions": [".md", ".txt"], "command": "nano -w"}, {"name": ".nix", "extensions": [".nix"], "command": "hx"}]' in page,
                  listed)
            dele = lambda name: b.request('/api/v1/plugin/files/delete?name=' + name, b'')[0]
            check('files: a file of a menu is deleted when asked for, and nothing else is',
                  dele('notes.md') == 200 and not os.path.exists(f'{tmp}/flake/notes.md')
                  and dele('../conf.toml') == 400 and dele('eznix/a.json') == 400 and dele('.hidden') == 400
                  and dele('sub/more.md') == 400 and os.path.exists(f'{tmp}/flake/sub/more.md'))
            open(f'{tmp}/flake/notes.md', 'w').write('x')
            exported = set(zipfile.ZipFile(io.BytesIO(b.request('/api/v1/plugin/system/export')[1])).namelist())
            check("system: the export's own exclude is read like a .gitignore too, dot-files being entries of it",
                  exported & set(made) == {'keep.md', 'sub/secret/x.nix', '.shown'}, sorted(exported))
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

            # What eznix-autocomplete leaves while it runs: a file holding its process number.
            running = lambda: b.json('/api/v1/ping')[1]['autocomplete_running']
            marker = f'{tmp}/state/autocomplete/.generating'
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(f'{tmp}/state/autocomplete/options.json', 'w') as f:
                f.write('[]')
            check('suggestions: a file that was generated is served', b.request('/autocomplete/options.json') == (200, b'[]'))
            check('suggestions: one that was not is answered with nothing, not as an error',
                  b.request('/autocomplete/choices.json') == (204, b''), b.request('/autocomplete/choices.json'))
            outside = [b.request(p)[0] for p in ('/autocomplete/../sessions.json', '/autocomplete/../../conf.toml',
                                                 '/autocomplete/%2e%2e/sessions.json', '/autocomplete//etc/hosts')]
            check('suggestions: no way out of their folder (the state beside it, the config, an absolute path)',
                  os.path.exists(f'{tmp}/state/sessions.json') and outside in ([404] * 4, [404, 404, 204, 404]), outside)
            check('no generator at work: the ping says so', ping['autocomplete_running'] is False, ping)
            with open(marker, 'w') as f:
                f.write(f'{os.getpid()}\n')
            check('one at work is reported', running() is True)
            gone = subprocess.Popen([sys.executable, '-c', 'pass'])
            gone.wait()
            with open(marker, 'w') as f:
                f.write(f'{gone.pid}\n')
            check('and one that was killed and left its mark behind is not', running() is False)
            os.remove(marker)

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
