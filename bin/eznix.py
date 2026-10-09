#!/usr/bin/env python3
"""
eznix — a web editor for Nix configurations (NixOS, nix-darwin, home-manager).

One file, standard library only. It serves the page in webroot/ and edits the *.json files in
a folder of the flake; the flake imports that folder through eznix.lib.jsonDir (json2nix.nix),
which merges them into the system.

Two ways it runs:

  for one person   as whoever starts it — by hand, on macOS, with home-manager. It starts its
                   own terminal (eznix-terminal) as a child unless told the terminals itself.
  as a service     an unprivileged account (NixOS). Each allowed user logs in with their system
                   password and has a terminal of their own, started for them by the system;
                   [terminals.<user>] says where each one is.

Nothing here runs as root or needs to. Commands that do (a rebuild) are typed, or put on a
button, with sudo in the user's own terminal.

  eznix                                   reads ./eznix.toml
  eznix --config FILE
  eznix --flake DIR --password PW         no config file at all
  eznix --generate-ca DIR [--san NAME]    make a local CA and server certificate, then exit

Configuration (eznix.toml; every key optional unless noted):

  flake           the flake being edited (default /etc/nixos, /etc/nix-darwin on macOS)
  config_dir      the folder of *.json files (default <flake>/eznix)
  exclude         paths in config_dir that are not configuration, relative to it: a file, or
                  a folder with everything under it
  default_file    file to open first
  state_dir       sessions, backups, autocomplete data, keys (default ~/.local/state/eznix)
  autocomplete_dir  where the generated suggestions are read from (default <state_dir>/autocomplete)
  webroot         the page's files (default: next to this file)
  listen, port    address and port (default 127.0.0.1:9090)
  hosts           extra host names to accept in requests; ["*"] accepts any. Behind a proxy
                  that changes the Host header, also the page's address ("https://name")
  cert, key       serve HTTPS with these (ca: the CA to offer for download on the login page)

  users           who may log in with their system password (default: whoever runs eznix,
                  when no plugin provides a login -- see plugins/password for the other way)
  auth_helper     program that checks a system password for an unprivileged eznix

  terminal        false: no terminal at all
  terminal_port   where eznix's own terminal listens when it starts one (default: port + 1)
  terminal_script the eznix-terminal program (default: next to this file)
  terminal_restart  command that restarts a user's terminal; {user} and {uid} are filled in
  terminal_end_on_logout  end the shell when its user logs out (default true)
  [terminals.NAME]  port, key_file, dir, shell — a terminal run by something else, for NAME

  theme, themes_dir, sections ("collapsed"/"expanded"), mode ("install"), terminal_auto_hide
  plugins_dir     folder of your own plugins, one folder each (see _load_plugins())
  [plugin.NAME]   settings for the plugin NAME; enabled = false leaves it out
  backups         how many saved versions of each file to keep (0: none)
  [[buttons]]     label, command, save_first, clear_first, menu, mode, static

The HTTP API the page uses is documented where it is handled, in Handler.do_GET/do_POST.
"""
import argparse
import atexit
import datetime
import email.utils
import getpass
import gzip
import hashlib
import html
import http.client
import http.server
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
from urllib.parse import urlparse, parse_qs

try:
    import pam as _pam
    _PAM = True
except ImportError:
    _PAM = None

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    _CRYPTO = True
except ImportError:
    _CRYPTO = False


# ── Settings ─────────────────────────────────────────────────────────────────────
# Everything below is set once, in main(), from the config file and the command line, and only
# read after that.
HERE = os.path.dirname(os.path.abspath(__file__))

FLAKE_DIR        = '/etc/nix-darwin' if sys.platform == 'darwin' else '/etc/nixos'
CONFIG_DIR       = None          # the folder of *.json files being edited
EXCLUDE          = []            # paths in it that are not configuration (see _excluded())
DEFAULT_FILE     = None          # file to prefer as the first tab
STATE_DIR        = os.path.expanduser('~/.local/state/eznix')
AUTOCOMPLETE_DIR = None          # generated suggestions; <state>/autocomplete unless set
WEBROOT          = None          # the page's own files
BACKUP_DIR       = None          # per-file backups, made on every save
BACKUP_COUNT     = 5

BIND_ADDR        = '127.0.0.1'
WEB_PORT         = 9090
TRUSTED_HOSTS    = set()         # extra Host names accepted by _valid_host(), and origins by _valid_origin(); "*" accepts any
CERT_FILE        = None          # HTTPS when both are set
KEY_FILE         = None
CA_FILE          = None          # offered for download on the login page
USE_TLS          = False         # set once the listening socket is actually wrapped

SYSTEM_LOGIN     = False         # system passwords are accepted -- see validate_credentials()
ALLOWED_USERS    = set()         # ...for these users
LOGINS           = []            # (plugin, check, user): ways to log in that plugins added
AUTH_HELPER      = None          # checks a system password when this process can't

# user -> {'port', 'key_file', 'dir', 'shell'}: the eznix-terminal that serves each login.
TERMINALS        = {}
TERMINAL_RESTART = None          # argv restarting a user's terminal, {user}/{uid} filled in
TERMINAL_END_ON_LOGOUT = True    # the shell belongs to a login: it ends when its user logs out
TERMINAL_SCRIPT  = None          # the eznix-terminal program on disk
TERMINAL_CURRENT_HASH = ''       # its hash, to tell when a running terminal is out of date
TERMINAL_AUTO_HIDE = True        # hide the open terminal panel on a click outside it

DEFAULT_THEME    = 'osx' if sys.platform == 'darwin' else 'nixos'
THEME            = DEFAULT_THEME
BUILTIN_THEMES   = ('nixos', 'dark', 'osx-light', 'gruvbox', 'osx-dark')
# Not a stylesheet but a choice between two, by the browser's system appearance: name ->
# (light, dark). The page resolves it; the login page gets both, each behind a media query.
AUTO_THEMES      = {'osx': ('osx-light', 'osx-dark')}
THEMES_DIR       = None          # folder of user themes, <name>.css each
CUSTOM_THEMES    = {}            # name -> {path, base, bg, border}; see _scan_custom_themes()
EZNIX_MODE       = None          # None or 'install': a second row of buttons, for an installer
SECTIONS_EXPANDED = False        # foldable sections start out shown
STATIC_BUTTONS   = []            # [[buttons]]: terminal buttons set where eznix is deployed
PLUGINS          = {}            # name -> {dir, scripts, styles, config}; see _load_plugins()
# The terminal's part of the page, in WEBROOT/terminal-panel/: loaded like a plugin's files
# (after the page's own script, talking to it through the same events), but only when a
# terminal is set up, and not a plugin -- everything else about the terminal is in this file.
TERMINAL_PANEL   = {'styles': ['xterm.css', 'terminal.css'],
                    'scripts': ['xterm.js', 'xterm-addon-fit.js', 'xterm-addon-webgl.js', 'terminal.js']}

# This machine's short name: in the page title and the installed app's name, so several eznix
# windows -- one per machine you look after -- can be told apart.
HOSTNAME         = socket.gethostname().split('.')[0] or 'localhost'

LOGIN_MAX_ATTEMPTS   = 5
LOGIN_WINDOW_SECONDS = 300       # failures older than this no longer count
_LOGIN_FAILURES  = {}            # ip -> [failure times within the window]
_LOGIN_LOCK      = threading.Lock()

# Fresh every start: the page reloads itself when it sees a new one.
PAGE_HASH        = ''            # checksum of everything the page is made of, set in main()
EZNIX_VERSION    = 'dev'
_STATIC_GZIP_CACHE = {}


def load_toml(path):
    if tomllib is None:
        sys.exit('eznix: reading a config file needs Python 3.11+, or the tomli package')
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        sys.exit(f'eznix: {path}: {e}')


def make_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    return ctx


def _build_sans(extra_sans=None):
    sans = [x509.DNSName('localhost'), x509.IPAddress(ipaddress.IPv4Address('127.0.0.1'))]
    seen = {'localhost', '127.0.0.1'}
    for san in (extra_sans or []):
        san = san.strip()
        if not san or san in seen or san in ('0.0.0.0', '::'):
            continue
        seen.add(san)
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(san)))
        except ValueError:
            sans.append(x509.DNSName(san))
    return sans


def _cert_san_strings(cert_path):
    with open(cert_path, 'rb') as f:
        cert = x509.load_pem_x509_certificate(f.read())
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        result = set()
        for name in ext.value:
            if isinstance(name, x509.DNSName):
                result.add(name.value)
            elif isinstance(name, x509.IPAddress):
                result.add(str(name.value))
        return result
    except x509.ExtensionNotFound:
        return set()


def _wanted_san_strings(extra_sans=None):
    result = set()
    for san in _build_sans(extra_sans):
        if isinstance(san, x509.DNSName):
            result.add(san.value)
        elif isinstance(san, x509.IPAddress):
            result.add(str(san.value))
    return result


def _generate_server_cert(out_dir, ca_key, ca_cert, extra_sans=None):
    srv_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_cert = (x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')]))
        .issuer_name(ca_cert.subject)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc))
        .not_valid_after(datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc))
        .add_extension(x509.SubjectAlternativeName(_build_sans(extra_sans)), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    for path, data in [
        (os.path.join(out_dir, 'localhost-key.pem'), srv_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())),
        (os.path.join(out_dir, 'localhost.pem'),      srv_cert.public_bytes(serialization.Encoding.PEM)),
    ]:
        with open(path, 'wb') as f:
            f.write(data)


def generate_local_ca(out_dir, extra_sans=None):
    """Ensure a local CA and server cert exist with the correct SANs.

    The CA is only generated once. The server cert is regenerated whenever
    the required SANs don't match the existing cert.
    Returns (ca_generated, srv_generated).
    """
    if not _CRYPTO:
        sys.exit('error: --generate-ca requires the cryptography package (pip install cryptography)')
    os.makedirs(out_dir, exist_ok=True)

    ca_key_path  = os.path.join(out_dir, 'ca-key.pem')
    ca_cert_path = os.path.join(out_dir, 'ca.pem')
    cert_path    = os.path.join(out_dir, 'localhost.pem')

    ca_generated = False
    if not os.path.exists(ca_key_path) or not os.path.exists(ca_cert_path):
        ca_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'eznix Local CA')])
        ca_cert = (x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc))
            .not_valid_after(datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                key_cert_sign=True, crl_sign=True, digital_signature=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                content_commitment=False, encipher_only=False, decipher_only=False,
            ), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        for path, data in [
            (ca_key_path,  ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())),
            (ca_cert_path, ca_cert.public_bytes(serialization.Encoding.PEM)),
        ]:
            with open(path, 'wb') as f:
                f.write(data)
        ca_generated = True
    else:
        with open(ca_key_path, 'rb') as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(ca_cert_path, 'rb') as f:
            ca_cert = x509.load_pem_x509_certificate(f.read())

    wanted = _wanted_san_strings(extra_sans)
    srv_generated = False
    if not os.path.exists(cert_path) or _cert_san_strings(cert_path) != wanted:
        _generate_server_cert(out_dir, ca_key, ca_cert, extra_sans)
        srv_generated = True

    return ca_generated, srv_generated


def generate_self_signed_cert(cert_path, key_path):
    if not _CRYPTO:
        sys.exit('error: --generate-cert requires the cryptography package (pip install cryptography)')
    key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    cert = (x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc))
        .not_valid_after(datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def check_pam(username, password):
    if _PAM is None:
        return False
    try:
        return _pam.pam().authenticate(username, password)
    except Exception:
        return False


def user_allowed(username):
    return not ALLOWED_USERS or username in ALLOWED_USERS


def validate_credentials(username, password):
    """Is this the right password for this user? Asked of every way to log in there is:

    The ones plugins added (LOGINS, see PluginApi.login()) -- the password plugin's one
    password from the config is such a one.

    The user's own system password, when SYSTEM_LOGIN, for the users in ALLOWED_USERS: asked of
    PAM in this process, or of AUTH_HELPER when this process isn't one PAM will answer for
    other people (an unprivileged service on Linux)."""
    ok = False
    for plugin, check, _user in LOGINS:
        try:
            ok = bool(check(username, password)) or ok
        except Exception as e:
            print(f'[auth] plugin {plugin}: {type(e).__name__}: {e}', file=sys.stderr)
    if ok:
        return True
    if SYSTEM_LOGIN and user_allowed(username):
        return check_helper(username, password) if AUTH_HELPER else check_pam(username, password)
    return False


def check_helper(username, password):
    """Password check by AUTH_HELPER, a separate privileged program, for when this process
    isn't one that PAM will check other people's passwords for."""
    if '\n' in username or '\n' in password:
        return False
    try:
        r = subprocess.run([AUTH_HELPER], input=f'{username}\n{password}\n', text=True,
                           capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f'[auth] helper failed: {e}', file=sys.stderr)
        return False
    return r.returncode == 0

def _session_from_cookie(headers):
    for part in headers.get('Cookie', '').split(';'):
        k, _, v = part.strip().partition('=')
        if k.strip() == 'eznix_session':
            return v.strip()
    return ''

# ── Login sessions ───────────────────────────────────────────────────────────────
# One per successful login: a random token in the browser's cookie, and here what it stands for
# -- who logged in, and until when. Kept by the token's
# hash, so the file they're saved in, next to the session key, is no use to whoever reads it;
# saved at all so that restarting the service doesn't log everyone out.
# As long as a browser will keep a cookie at all: browsers cap that at 400 days however much
# is asked for, and one with no lifetime given is thrown away when the browser quits. Renewed
# every time the page is loaded (see _renew_session()), so in practice a login only ends by
# logging out, or by not opening eznix for over a year.
SESSION_LIFETIME = 400 * 24 * 3600
_SESSIONS        = {}               # sha256(token) -> {'user': str, 'expires': unix time}
_SESSION_SEEN    = {}               # sha256(token) -> when it last made a request; not saved
_SESSIONS_FILE   = None
_SESSIONS_LOCK   = threading.Lock()
USE_TLS          = False            # set once the listening socket is actually wrapped

def _token_id(token):
    return hashlib.sha256(token.encode()).hexdigest()

def _load_sessions():
    try:
        with open(_SESSIONS_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return
    now = time.time()
    with _SESSIONS_LOCK:
        for k, v in data.items():
            if isinstance(v, dict) and v.get('expires', 0) > now:
                _SESSIONS[k] = {'user': str(v.get('user', '')), 'expires': v['expires']}

def _save_sessions():
    """Call with _SESSIONS_LOCK held."""
    if not _SESSIONS_FILE:
        return
    try:
        tmp = _SESSIONS_FILE + '.new'
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
            json.dump(_SESSIONS, f)
        os.replace(tmp, _SESSIONS_FILE)
    except OSError as e:
        print(f'[auth] could not save sessions: {e}', file=sys.stderr)

def _new_session(user):
    token = secrets.token_hex(32)
    with _SESSIONS_LOCK:
        _SESSIONS[_token_id(token)] = {'user': user, 'expires': time.time() + SESSION_LIFETIME}
        _save_sessions()
    return token

def _session(headers):
    """The session this request's cookie belongs to ({'user', 'expires'}), or None."""
    token = _session_from_cookie(headers)
    if not token:
        return None
    with _SESSIONS_LOCK:
        s = _SESSIONS.get(_token_id(token))
        if s and s['expires'] <= time.time():
            del _SESSIONS[_token_id(token)]
            _save_sessions()
            s = None
        if s:
            _SESSION_SEEN[_token_id(token)] = time.time()
        return s

def _session_cookie(token, max_age=SESSION_LIFETIME):
    """Set-Cookie value. Max-Age is what makes a login outlast the browser being quit: without
    it the cookie only lives as long as the browser process does."""
    secure = '; Secure' if USE_TLS else ''
    return f'eznix_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}'

def _renew_session(headers):
    """Push this session's expiry out again and return the cookie to send with it, or None.
    Called when the page itself is loaded -- so a login lasts SESSION_LIFETIME past the last
    time it was actually used, not past the day it was made."""
    token = _session_from_cookie(headers)
    with _SESSIONS_LOCK:
        s = _SESSIONS.get(_token_id(token)) if token else None
        if not s:
            return None
        s['expires'] = time.time() + SESSION_LIFETIME
        _save_sessions()
    return _session_cookie(token)

def _end_session(headers):
    """Forget this request's session. Returns its user unless that person is still at it in
    another browser, else None. "Still at it" means another of their sessions made a request in
    the last minute -- an open tab polls every few seconds -- not merely that one exists: a
    login whose browser is closed, or whose cookie was thrown away, sits in the list until it
    expires, and shouldn't keep a shell alive for a month."""
    token = _session_from_cookie(headers)
    with _SESSIONS_LOCK:
        s = _SESSIONS.pop(_token_id(token), None) if token else None
        if not s:
            return None
        _SESSION_SEEN.pop(_token_id(token), None)
        _save_sessions()
        recent = time.time() - 60
        active = any(o['user'] == s['user'] and _SESSION_SEEN.get(k, 0) > recent
                     for k, o in _SESSIONS.items())
        return None if active else s['user']

def check_auth(headers):
    return _session(headers) is not None

def _terminal_for(user):
    """The terminal that serves this login: {'port', 'key', 'config_hash'}, or None when they
    have none. Every terminal is its own eznix-terminal process, running as its user, with a
    secret of its own in key_file -- so the people allowed in can't reach each other's shells.

    'config_hash' is what that process's own CONFIG_HASH should be if it was started the way
    the config says: the same formula as eznix-terminal.py's, over the same four values."""
    # '*': the one eznix started itself, run by hand -- whoever logs in there is acting as
    # the person running it.
    t = TERMINALS.get(user) or TERMINALS.get('*')
    if not t:
        return None
    try:
        with open(t['key_file']) as f:
            key = f.read().strip()
    except OSError:
        return None
    raw = {'port': t['port'], 'key_file': t['key_file'], 'dir': t.get('dir'), 'shell': t.get('shell')}
    chash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:16]
    return {'port': t['port'], 'key': key, 'config_hash': chash}


# Run by hand there is no module to run a terminal alongside: eznix starts one itself, as a
# child, for whoever is running it (see _start_own_terminal()). Kept here so that Restart
# Terminal can restart it.
_OWN_TERMINAL = {'proc': None, 'argv': None}

def _start_own_terminal():
    if not _OWN_TERMINAL['argv']:
        return
    old = _OWN_TERMINAL['proc']
    if old and old.poll() is None:
        old.terminate()
        try:
            old.wait(timeout=3)
        except subprocess.TimeoutExpired:
            old.kill()
    _OWN_TERMINAL['proc'] = subprocess.Popen(_OWN_TERMINAL['argv'])


def _terminal_end(user):
    """Ask this user's eznix-terminal.py to end the running shell (see TERMINAL_END_ON_LOGOUT). Best effort."""
    term = _terminal_for(user)
    if not term:
        return
    try:
        conn = http.client.HTTPConnection('127.0.0.1', term['port'], timeout=3)
        conn.request('POST', '/terminal/end', headers={'Cookie': f'eznix_session={term["key"]}', 'Content-Length': '0'})
        conn.getresponse().read()
        conn.close()
    except Exception as e:
        print(f'[terminal] could not end the shell: {e}', file=sys.stderr)


def _login_retry_after(ip):
    """Seconds until `ip` may attempt to log in again, or 0 if it isn't currently rate-limited.
    Also prunes failures older than LOGIN_WINDOW_SECONDS so _LOGIN_FAILURES doesn't grow
    unbounded over a long-running process."""
    now = time.time()
    with _LOGIN_LOCK:
        attempts = [t for t in _LOGIN_FAILURES.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
        if attempts:
            _LOGIN_FAILURES[ip] = attempts
        else:
            _LOGIN_FAILURES.pop(ip, None)
        if len(attempts) < LOGIN_MAX_ATTEMPTS:
            return 0
        return max(1, int(LOGIN_WINDOW_SECONDS - (now - attempts[0])))


def _record_login_failure(ip):
    """Returns the attempt count within the current window after recording this one, for the
    [auth] log line in do_POST -- avoids a second lock-protected read just to report it."""
    with _LOGIN_LOCK:
        attempts = _LOGIN_FAILURES.setdefault(ip, [])
        attempts.append(time.time())
        return len(attempts)


def _clear_login_failures(ip):
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.pop(ip, None)



def _flatten_stem(rel):
    """Turn a CONFIG_DIR-relative path like 'services/nginx.json' into a flat, collision-safe
    backup stem ('services--nginx') so BACKUP_DIR itself never needs subdirectories."""
    return os.path.splitext(rel)[0].replace(os.sep, '--').replace('/', '--')


def backup_config(path):
    """Copy path into BACKUP_DIR, pruning to BACKUP_COUNT newest backups sharing its stem."""
    if BACKUP_COUNT <= 0 or not os.path.exists(path):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    rel = os.path.relpath(path, os.path.realpath(CONFIG_DIR))
    stem = _flatten_stem(rel)
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(BACKUP_DIR, f'{stem}-{ts}.json')
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(BACKUP_DIR, f'{stem}-{ts}-{i}.json')
        i += 1
    shutil.copy2(path, dest)
    prefix = f'{stem}-'
    backups = [f for f in os.listdir(BACKUP_DIR) if f.startswith(prefix) and f.endswith('.json')]
    backups.sort(key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)), reverse=True)
    for old in backups[BACKUP_COUNT:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass


def list_backups(stem):
    items = []
    prefix = f'{stem}-'
    if os.path.isdir(BACKUP_DIR):
        for name in os.listdir(BACKUP_DIR):
            if not (name.startswith(prefix) and name.endswith('.json')):
                continue
            st = os.stat(os.path.join(BACKUP_DIR, name))
            items.append({'name': name, 'mtime': st.st_mtime, 'size': st.st_size})
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return items


def resolve_backup_path(name):
    """Return the absolute path for a backup file name, or None if invalid/outside BACKUP_DIR."""
    if not name or '/' in name or '\\' in name or name in ('.', '..'):
        return None
    base = os.path.realpath(BACKUP_DIR)
    full = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(full) != base or not os.path.isfile(full):
        return None
    return full


def _is_disabled_folder_name(name):
    """True for a single path segment marking a disabled folder, e.g. '.services.disabled'.

    The leading dot piggybacks on the dotdir skip that already excludes .eznix-backups from
    both list_config_folders() and json2nix.nix's walk() — no change to json2nix.nix needed for
    a disabled folder (and everything nested inside it) to drop out of the Nix merge."""
    return name.startswith('.') and name.endswith('.disabled') and len(name) > len('..disabled')


def _excluded(rel):
    """Is this path, relative to CONFIG_DIR, one `exclude` leaves out: listed itself, or inside
    a listed folder? Excluded paths are no tabs and no folders, and can't be read or written
    through the editor. For a config_dir that holds other JSON than configuration -- the
    flake's own root, with its package.json. json2nix.nix takes the same list, and the two
    have to agree: left out here only, a file is still built; there only, it is a tab that
    changes nothing."""
    rel = rel.replace('\\', '/').strip('/')
    return any(rel == e or rel.startswith(e + '/') for e in EXCLUDE)


def resolve_config_path(name):
    """Return the absolute path for a config file name inside CONFIG_DIR, or None if invalid.

    Falls back to DEFAULT_FILE when name is empty, so a caller that hasn't learned the file
    list yet still resolves to a sensible file. Does not require the file to already exist,
    since file/save uses this to create new tabs. Subpaths (e.g. "services/nginx.json") are
    allowed for organizing tabs into folders; this only keeps writes inside CONFIG_DIR by
    construction (an authenticated user here already has full terminal access to the machine,
    so this is a correctness guard against typos, not a security boundary).

    A name ending in ".json.disabled" (a file disabled by renaming it via /api/v1/file/rename —
    see list_config_files()) resolves just like its ".json" counterpart, since disabling only
    renames the file; its content is still read/saved the same way.
    """
    name = name or DEFAULT_FILE
    if not name or os.path.basename(name) == 'custom-options.json':
        return None
    if not (name.endswith('.json') or name.endswith('.json.disabled')):
        return None
    parts = name.replace('\\', '/').split('/')
    if os.path.isabs(name) or any(p in ('', '.', '..') for p in parts) or _excluded(name):
        return None
    base = os.path.realpath(CONFIG_DIR)
    full = os.path.realpath(os.path.join(base, name))
    if os.path.commonpath([base, full]) != base:
        return None
    return full


def list_config_files():
    """Recursively list the *.json tabs under CONFIG_DIR as relative POSIX paths.

    Skips dotdirs (in particular BACKUP_DIR's default name, .eznix-backups, when it lives
    inside CONFIG_DIR) so backup files never show up as tabs — except a disabled folder
    (_is_disabled_folder_name()), which is still walked so its files keep showing up (as
    disabled tabs) in the UI even though json2nix.nix skips it at eval time. Also includes
    *.json.disabled files (individually disabled tabs, see /api/v1/file/rename) alongside
    their *.json siblings.
    """
    base = os.path.realpath(CONFIG_DIR)
    names = []
    for root, dirs, filenames in os.walk(base):
        rel_of = lambda n: os.path.relpath(os.path.join(root, n), base).replace(os.sep, '/')
        dirs[:] = [d for d in dirs if (not d.startswith('.') or _is_disabled_folder_name(d)) and not _excluded(rel_of(d))]
        for fn in filenames:
            if fn == 'custom-options.json':
                continue
            if not (fn.endswith('.json') or fn.endswith('.json.disabled')):
                continue
            rel = rel_of(fn)
            if not _excluded(rel):
                names.append(rel)
    names.sort()
    return names


def list_config_folders():
    """Recursively list every subdirectory under CONFIG_DIR as a relative POSIX path.

    Unlike the folders implied by list_config_files(), this also reports directories that
    don't (yet) contain any *.json file, so a folder created via /api/v1/folder/create still
    shows up as an (empty) tab group after a reload. A disabled folder (dot-prefixed, see
    _is_disabled_folder_name()) is listed too — and still walked into, so any subfolders
    nested inside it are listed as well.
    """
    base = os.path.realpath(CONFIG_DIR)
    names = []
    for root, dirs, _filenames in os.walk(base):
        rel_of = lambda n: os.path.relpath(os.path.join(root, n), base).replace(os.sep, '/')
        dirs[:] = [d for d in dirs if (not d.startswith('.') or _is_disabled_folder_name(d)) and not _excluded(rel_of(d))]
        names += [rel_of(d) for d in dirs]
    names.sort()
    return names


def resolve_folder_path(name):
    """Like resolve_config_path, but for a directory rather than a *.json file — no extension
    requirement, and the directory need not already exist."""
    if not name:
        return None
    parts = name.replace('\\', '/').split('/')
    if os.path.isabs(name) or any(p in ('', '.', '..') for p in parts) or _excluded(name):
        return None
    base = os.path.realpath(CONFIG_DIR)
    full = os.path.realpath(os.path.join(base, name))
    if os.path.commonpath([base, full]) != base:
        return None
    return full


def _config_stem(name):
    """Resolve name to a config path and return its flattened backup stem, or None if invalid."""
    path = resolve_config_path(name)
    if path is None:
        return None
    rel = os.path.relpath(path, os.path.realpath(CONFIG_DIR))
    return _flatten_stem(rel)


_THEME_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]*$')


def _scan_custom_themes(themes_dir):
    """User themes: every <name>.css in themes_dir. A theme file is the same thing a built-in
    theme-<name>.css is — a :root block of variables — except it doesn't have to be complete: the
    page loads a built-in theme underneath it (its base), so a file only sets what it wants to
    change, and keeps working when a later version adds a variable it has never heard of. The
    base is "nixos" unless the file says otherwise in a comment near its top:

        /* base: light */

    bg/border are what its swatch in the header is painted with, read from the file's own --bg
    and --accent when it sets them as plain values. A name that's already a built-in theme is
    skipped rather than allowed to replace it."""
    themes = {}
    if not themes_dir:
        return themes
    try:
        names = sorted(os.listdir(themes_dir))
    except OSError as e:
        print(f'themes_dir: {e}', file=sys.stderr)
        return themes
    for fname in names:
        name, ext = os.path.splitext(fname)
        if ext != '.css' or not _THEME_NAME_RE.match(name):
            continue
        if name in BUILTIN_THEMES or name in AUTO_THEMES:
            print(f'themes_dir: {fname} skipped ("{name}" is a built-in theme)', file=sys.stderr)
            continue
        path = os.path.join(themes_dir, fname)
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                css = f.read()
        except OSError:
            continue
        m = re.search(r'/\*\s*base:\s*([a-z0-9_-]+)\s*\*/', css[:2000])
        base = m.group(1) if m else 'nixos'
        if base not in BUILTIN_THEMES:
            base = 'nixos'

        def colour(var):
            c = re.search(r'--' + var + r'\s*:\s*(#[0-9a-fA-F]{3,8})\s*;', css)
            return c.group(1) if c else None
        themes[name] = {'path': path, 'base': base, 'bg': colour('bg'), 'border': colour('accent')}
    return themes


def _theme_links(theme):
    """The stylesheet link(s) for a theme, for login.html: a custom theme is its base plus its
    own file on top (see _scan_custom_themes())."""
    if theme in AUTO_THEMES:
        light, dark = AUTO_THEMES[theme]
        return ('<link rel="stylesheet" href="theme-%s.css" media="(prefers-color-scheme: light)">\n'
                '<link rel="stylesheet" href="theme-%s.css" media="(prefers-color-scheme: dark)">' % (light, dark))
    link = '<link rel="stylesheet" href="theme-%s.css">'
    custom = CUSTOM_THEMES.get(theme)
    return (link % custom['base'] + '\n' if custom else '') + link % theme


class PluginError(Exception):
    """Raised by a plugin's handler to answer with an error: PluginError(400, 'why')."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class PluginDownload:
    """Returned by a plugin's handler to send a file instead of JSON."""
    def __init__(self, data, content_type, filename):
        self.data, self.content_type, self.filename = data, content_type, filename


class PluginRequest:
    """What a plugin's handler is given: the query string as a dict, the request body, and who
    is logged in."""
    def __init__(self, query, body, user):
        self.query, self.body, self.user = query, body, user


class PluginApi:
    """Handed to the setup(api) function of a plugin's server file (the "server" entry of its
    plugin.json), once, when eznix starts. The plugin registers what it answers:
        api.get('files', handler)      GET  /api/v1/plugin/NAME/files
        api.post('import', handler)    POST /api/v1/plugin/NAME/import
    A handler takes a PluginRequest and returns something JSON can hold, or an api.Download;
    raising api.Error(status, message) answers with that error. Requests reach a handler only
    from a logged-in browser. Everything else here is for reading:
        api.config     this plugin's [plugin.NAME] table
        api.flake, api.config_dir, api.state_dir, api.hostname
        api.page       set it to change what the page gets as eznix.config.NAME (default: config)
    and api.login(check, user) adds a way to log in."""
    Error, Download = PluginError, PluginDownload

    def __init__(self, name, config):
        self.name, self.config, self.page = name, config, config
        self.flake, self.config_dir, self.state_dir, self.hostname = FLAKE_DIR, CONFIG_DIR, STATE_DIR, HOSTNAME
        self.routes = {}

    def login(self, check, user=None):
        """Add a way to log in: check(username, password) says whether that is right. `user`,
        when the method is for one known name, lets the login page offer it."""
        LOGINS.append((self.name, check, user))

    def get(self, path, handler):
        self.routes[('GET', path.strip('/'))] = handler

    def post(self, path, handler):
        self.routes[('POST', path.strip('/'))] = handler


def _load_plugins(cfg):
    """PLUGINS: the page plugins to load. A plugin is a folder holding a plugin.json --
        {"name": "terminal", "styles": ["a.css"], "scripts": ["a.js", "b.js"]}
    -- and the files it lists, served at /plugins/NAME/ and loaded into the page in that order,
    after the page's own script (the events it can listen for are listed there, under
    "Plugins" in index.html). Whatever [plugin.NAME] holds in the configuration reaches it as
    eznix.config.NAME. Plugins come from WEBROOT/plugins (the ones eznix ships) and from
    plugins_dir (your own); a folder there named like a shipped one is skipped.

    A plugin may also name a Python file as "server": it is loaded into this process and its
    setup(api) registers what it answers under /api/v1/plugin/NAME/ (see PluginApi). So a
    plugin runs with everything eznix itself can do, in the page and on the machine: installing
    one is trusting it like any program. [plugin.NAME] enabled = false leaves one out.

    The rule for what is a plugin: it needs nothing from the system it runs on. The terminal
    does (a process per user, run by a service manager), so it is part of eznix itself -- see
    TERMINAL_PANEL."""
    found = {}
    settings = cfg.get('plugin') if isinstance(cfg.get('plugin'), dict) else {}
    for base in (os.path.join(WEBROOT, 'plugins'), cfg.get('plugins_dir')):
        try:
            names = sorted(os.listdir(base)) if base else []
        except OSError:
            names = []
        for name in names:
            folder = os.path.join(base, name)
            try:
                with open(os.path.join(folder, 'plugin.json')) as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                continue
            files = {k: manifest.get(k) or [] for k in ('styles', 'scripts')}
            ok = (re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name) and manifest.get('name') == name
                  and all(isinstance(f, str) and _plugin_file(folder, f)
                          for group in files.values() for f in group))
            if not ok:
                print(f'eznix: plugin folder {folder} skipped: its plugin.json needs "name": '
                      f'"{name}" and lists of existing files', file=sys.stderr)
                continue
            conf = settings.get(name) if isinstance(settings.get(name), dict) else {}
            if name in found or conf.get('enabled') is False:
                continue
            api = PluginApi(name, {k: v for k, v in conf.items() if k != 'enabled'})
            server = manifest.get('server')
            if server:
                # A plugin that fails to start is left out whole, rather than half working.
                try:
                    spec = importlib.util.spec_from_file_location(f'eznix_plugin_{name}', _plugin_file(folder, server))
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.setup(api)
                except Exception as e:
                    print(f'eznix: plugin {name} not loaded: {type(e).__name__}: {e}', file=sys.stderr)
                    LOGINS[:] = [l for l in LOGINS if l[0] != name]
                    continue
            found[name] = dict(files, dir=folder, config=api.page, routes=api.routes, server=server)
    return found


def _plugin_file(folder, rel):
    """The file `rel` names inside a plugin's folder, or None when it isn't one there."""
    path = os.path.realpath(os.path.join(folder, rel))
    inside = path.startswith(os.path.realpath(folder) + os.sep)
    return path if inside and os.path.isfile(path) else None


def _render_index():
    """index.html with every %%EZNIX_...%% setting filled in, except the page checksum itself
    (which is computed from this -- see _compute_page_hash()). Everything used here is fixed
    once main() has read the configuration."""
    tags = {'styles': '<link rel="stylesheet" href="plugins/%s/%s">',
            'scripts': '<script src="plugins/%s/%s"></script>'}
    plugin = {kind: '\n'.join(
                  [tag.replace('plugins/%s', 'terminal-panel') % f for f in TERMINAL_PANEL[kind] if TERMINALS]
                  + [tag % (name, html.escape(f)) for name, p in PLUGINS.items() for f in p[kind]])
              for kind, tag in tags.items()}
    # "</" escaped so nothing in a setting (a button's command, say) can close the <script>
    # block this is embedded into.
    config = {name: p['config'] for name, p in PLUGINS.items()}
    if TERMINALS:
        config['terminal'] = {'auto_hide': TERMINAL_AUTO_HIDE, 'buttons': STATIC_BUTTONS,
                              'script_hash': TERMINAL_CURRENT_HASH}
    plugin_config = json.dumps(config).replace('</', '<\\/')
    return (open(os.path.join(WEBROOT, 'index.html')).read()
        .replace('%%EZNIX_PLUGIN_STYLES%%', plugin['styles'])
        .replace('%%EZNIX_PLUGIN_SCRIPTS%%', plugin['scripts'])
        .replace('%%EZNIX_PLUGIN_CONFIG%%', plugin_config)
        .replace('%%EZNIX_HOSTNAME%%', html.escape(HOSTNAME))
        .replace('%%EZNIX_THEME%%', THEME)
        .replace('%%EZNIX_CUSTOM_THEMES%%', json.dumps(
            {n: {k: t[k] for k in ('base', 'bg', 'border')} for n, t in CUSTOM_THEMES.items()}))
        .replace('%%EZNIX_BACKUP%%', 'true' if BACKUP_COUNT > 0 else 'false')
        .replace('%%EZNIX_MODE%%', json.dumps(EZNIX_MODE))
        .replace('%%EZNIX_SECTIONS_EXPANDED%%', 'true' if SECTIONS_EXPANDED else 'false')
        .replace('%%EZNIX_FLAKE%%', FLAKE_DIR.replace('\\', '\\\\').replace("'", "\\'"))
        .replace('%%EZNIX_HOSTNAME%%', HOSTNAME.replace('\\', '\\\\').replace("'", "\\'"))
        .replace('%%EZNIX_VERSION%%', EZNIX_VERSION)
    )


def _compute_page_hash():
    """PAGE_HASH: one checksum of everything a browser gets from this server -- the page as
    rendered (so every setting baked into it), every file under WEBROOT, the user themes and
    plugins, and this program itself. The page is told the value it was built with and /api/v1/ping reports
    the current one; a page seeing a different value reloads. That is the whole of update
    detection: nothing is compared field by field, so nothing can be forgotten. Autocomplete
    data is left out -- it changes while the server runs and has its own stamp in the ping."""
    h = hashlib.sha256()
    h.update(_render_index().encode('utf-8'))
    paths = [os.path.abspath(__file__)] + sorted(t['path'] for t in CUSTOM_THEMES.values())
    outside = [p['dir'] for p in PLUGINS.values() if not p['dir'].startswith(WEBROOT + os.sep)]
    for root, dirs, names in [w for top in [WEBROOT] + outside for w in os.walk(top)]:
        dirs[:] = sorted(d for d in dirs if d != 'autocomplete' and not d.startswith('.'))
        paths += [os.path.join(root, n) for n in sorted(names) if n != 'index.html']
    for path in paths:
        try:
            with open(path, 'rb') as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            pass
    return h.hexdigest()[:16]


def _read_version():
    """EZNIX_VERSION — content of WEBROOT/VERSION, written by the Nix derivation (see
    nix/packages.nix). Missing (a plain git checkout, no Nix build) or empty falls back
    to 'dev', same convention the frontend's own version display already used."""
    try:
        with open(os.path.join(WEBROOT, 'VERSION')) as f:
            return f.read().strip() or 'dev'
    except OSError:
        return 'dev'


def _compute_file_hash(path):
    """Truncated sha256 of a single file — used for
    TERMINAL_CURRENT_HASH (see there). Returns '' if path is unset or unreadable, same as an
    ordinary "nothing to compare against" case rather than an error."""
    if not path:
        return ''
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return ''


def _terminal_running_status(term):
    """Best-effort fetch of the *actually running* eznix-terminal.py's own SELF_HASH/CONFIG_HASH, via
    its /terminal/hash status endpoint (loopback only, see eznix-terminal.py) -- not the WS 'ready'
    message, which only ever arrives once a client has the terminal panel open. Included in
    _ping_payload() so initRestartWatcher() can keep the restart notification accurate even
    when the panel is closed (previously: reloading the GUI reset the frontend's in-memory
    _terminalRunningHash to null, and nothing repopulated it unless the panel happened to be
    open, silently hiding a notification that was still genuinely true). Returns {} on any
    failure -- the terminal not up yet, a slow response, no terminal at all -- so a transient
    miss just leaves this one ping tick's fields absent rather than reporting a wrong hash."""
    if not term:
        return {}
    try:
        conn = http.client.HTTPConnection('127.0.0.1', term['port'], timeout=2)
        try:
            conn.request('GET', '/terminal/hash', headers={'Cookie': f'eznix_session={term["key"]}'})
            resp = conn.getresponse()
            data = resp.read()
            if resp.status != 200:
                return {}
            return json.loads(data)
        finally:
            conn.close()
    except Exception:
        return {}


def _autocomplete_stamp():
    """When the autocomplete data last changed -- so the page reloads it whoever regenerated it,
    and however: its own button, a command in the terminal, a rebuild."""
    d = AUTOCOMPLETE_DIR or os.path.join(WEBROOT, 'autocomplete')
    stamp = 0
    try:
        for name in os.listdir(d):
            if name.endswith('.json'):
                stamp = max(stamp, int(os.stat(os.path.join(d, name)).st_mtime))
    except OSError:
        pass
    return stamp


def _ping_payload(user=None):
    """GET /api/v1/ping's whole response, polled by initRestartWatcher() (index.html): the
    page checksum (see _compute_page_hash()), the autocomplete stamp, and what the terminal
    restart notice compares."""
    _term = _terminal_for(user)
    _running = _terminal_running_status(_term)
    return {
        'page': PAGE_HASH,
        'theme': THEME,
        'autocomplete_stamp': _autocomplete_stamp(),
        'terminal_current_hash': TERMINAL_CURRENT_HASH,
        'terminal_running_hash': _running.get('hash'),
        'terminal_config_hash': _term['config_hash'] if _term else '',
        'terminal_running_config_hash': _running.get('config_hash'),
    }


def _read_login_page(error=''):
    # Every name there is a login for, when that is known.
    names = sorted({u for _p, _c, u in LOGINS if u} | (ALLOWED_USERS if SYSTEM_LOGIN else set()))
    if len(names) > 1:
        # A <select> here (tried first) can only ever submit one of these exact values, but
        # browsers' saved-password heuristics look for an <input> paired with the password field --
        # a <select> isn't recognized as a username field at all, so Brave/Chrome saved the password
        # with no username attached. A plain <input> with a <list>-linked <datalist> (tried second)
        # fixed that but broke autofill in a different way: Chromium suppresses its own saved-
        # password suggestion dropdown on any input that has a `list` attribute at all, since the
        # datalist popup and the browser's native autofill popup would otherwise compete for the
        # same space -- confirmed this reproduces on any <input list=...> paired with a password
        # field, on any site, not something specific to this app. A hand-rolled dropdown wired to
        # the input's own focus/typing (tried third) hit the exact same problem one level up:
        # screenshotted on a real login, our dropdown and the browser's own suggestion (both opening
        # on focus) stacked on top of each other. There's no documented way to make a suggestion UI
        # and the browser's native autofill popup coexist at that same moment -- checked Chromium's
        # own password-forms guidance and web.dev's sign-in-form best practices, neither covers it --
        # so this version doesn't try: the field is an entirely ordinary <input> that autofill never
        # has any reason to react to, and the picker is a separate, explicit action (a small arrow
        # button) rather than anything tied to focusing or typing in the field at all. None of this
        # is a security boundary either way: user_allowed() re-checks the submitted username against
        # ALLOWED_USERS server-side regardless of how it arrived, since anyone can POST /login with
        # an arbitrary username directly, with or without a picker in front of it.
        users_json = json.dumps(names)
        username_field = f'''<div class="login-suggest-wrap">
      <input id="u" name="username" type="text" autocomplete="username" autofocus>
      <button type="button" class="login-suggest-arrow" id="u-arrow" tabindex="-1" aria-label="Choose a username">&#9662;</button>
      <div class="login-suggest hidden" id="u-suggest"></div>
    </div>
    <script>
    (function() {{
      var users = {users_json};
      var inp = document.getElementById('u');
      var arrow = document.getElementById('u-arrow');
      var list = document.getElementById('u-suggest');
      function render() {{
        list.innerHTML = '';
        users.forEach(function(u) {{
          var item = document.createElement('div');
          item.className = 'login-suggest-item';
          item.textContent = u;
          item.addEventListener('mousedown', function(e) {{
            e.preventDefault();
            inp.value = u;
            list.classList.add('hidden');
          }});
          list.appendChild(item);
        }});
      }}
      render();
      // The only way this ever opens -- never on the input's own focus or typing, both of which
      // the browser's native autofill also reacts to on this same field (see the comment above).
      // An explicit click is a separate, deliberate action that can't collide with that.
      arrow.addEventListener('mousedown', function(e) {{
        e.preventDefault();
        list.classList.toggle('hidden');
      }});
      document.addEventListener('mousedown', function(e) {{
        if (e.target !== arrow && !list.contains(e.target)) list.classList.add('hidden');
      }});
    }})();
    </script>'''
    else:
        # Exactly one user can log in, so the field comes filled in.
        _known = f' value="{html.escape(names[0])}"' if names else ''
        username_field = f'<input id="u" name="username" type="text" autocomplete="username"{_known} autofocus>'
    ca_link = ''
    if CA_FILE and os.path.exists(CA_FILE):
        ca_link = '<div class="login-ca-link"><a href="/download-ca" tabindex="-1">Download CA certificate</a></div>'
    path = os.path.join(WEBROOT, 'login.html')
    try:
        return (open(path).read()
                .replace('%%EZNIX_ERROR%%', error)
                .replace('%%EZNIX_THEME_LINKS%%', _theme_links(THEME))
                .replace('%%EZNIX_HOSTNAME%%', html.escape(HOSTNAME))
                .replace('%%EZNIX_USERNAME_FIELD%%', username_field)
                .replace('%%EZNIX_CA_LINK%%', ca_link))
    except FileNotFoundError:
        return f'<html><body><form method="post" action="/login"><input name="username"><input name="password" type="password"><button>Sign in</button></form><p>{error}</p></body></html>'


def _recv_until_double_crlf(sock, chunk=4096):
    """Read from a raw socket until the HTTP header terminator; returns (header_bytes including
    the terminator, any already-read bytes past it) -- used by _proxy_terminal() to forward
    eznix-terminal.py's handshake response without needing http.client on either leg."""
    buf = b''
    while b'\r\n\r\n' not in buf:
        data = sock.recv(chunk)
        if not data:
            return b'', b''
        buf += data
    idx = buf.find(b'\r\n\r\n') + 4
    return buf[:idx], buf[idx:]


def _pipe(src, dst):
    """One direction of _proxy_terminal()'s byte relay -- runs until src is closed or errors,
    then shuts dst down too. Without this, whichever side dies first (e.g. eznix-terminal.py itself,
    restarted via "Restart Terminal") left the *other* direction's blocking recv() with no way to
    ever learn its peer is gone -- confirmed as a real, reproduced hang, since a browser sitting
    on an idle WS connection has no reason to send anything that would otherwise surface the dead
    backend. Deliberately shutdown(SHUT_RDWR), not just close(): closing a socket from a thread
    other than the one blocked in recv() on it is not reliably enough to unblock that call --
    confirmed empirically (a plain dst.close() here left the peer thread's recv() hanging
    indefinitely on macOS, even though the fd was genuinely closed and the TCP connection had
    already gone to CLOSE_WAIT). shutdown() is the actual POSIX-documented way to force a
    concurrent blocking call on the same socket to return; close() still runs after to release
    the fd once nothing is blocked on it anymore."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            dst.close()
        except OSError:
            pass


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        self.directory = WEBROOT
        return super().translate_path(path)

    def end_headers(self):
        # Files served from WEBROOT often come from the Nix store, where mtimes are normalized
        # to a fixed value for build reproducibility — Last-Modified-based conditional caching
        # would then treat genuinely new content as unchanged. Disable caching outright instead.
        # /autocomplete/* opts out of this (see _serve_autocomplete()): those files live in a
        # real writable directory and get a genuinely fresh mtime every time eznix-autocomplete
        # regenerates them, so Last-Modified-based caching is trustworthy there.
        if not getattr(self, '_no_default_cache_control', False):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _deny(self, error=''):
        accept = self.headers.get('Accept', '')
        if 'text/html' in accept:
            page = _read_login_page(error).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        else:
            self.send_response(401)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Unauthorized\n')

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/login':
            ip = self.client_address[0]
            retry_after = _login_retry_after(ip)
            if retry_after:
                print(f'[auth] {ip} rate-limited, retry in {retry_after}s')
                self._deny(f'Too many failed attempts. Try again in {retry_after}s.')
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8', errors='replace')
            params = {k: v[0] for k, v in parse_qs(body).items()}
            username = params.get('username', '')
            password = params.get('password', '')
            if validate_credentials(username, password):
                _clear_login_failures(ip)
                print(f'[auth] login succeeded for {username!r} from {ip}')
                self.send_response(303)
                self.send_header('Location', '/')
                self.send_header('Set-Cookie', _session_cookie(_new_session(username)))
                self.end_headers()
            else:
                count = _record_login_failure(ip)
                print(f'[auth] login failed for {username!r} from {ip} ({count}/{LOGIN_MAX_ATTEMPTS} attempts)')
                self._deny('Invalid username or password.')
            return
        if not _valid_host(self.headers) or not _valid_origin(self.headers):
            self.send_error(403); return
        if not check_auth(self.headers):
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"Unauthorized"}')
            return
        if parsed.path == '/api/v1/file/save':
            try:
                qs = parse_qs(parsed.query)
                target = resolve_config_path(qs.get('file', [None])[0])
                if not target:
                    resp = b'{"error":"invalid file name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                backup_config(target)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, 'w') as f:
                    json.dump(body, f, indent=2)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/file/delete':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                target = resolve_config_path(body.get('file', ''))
                if not target or not os.path.isfile(target):
                    resp = b'{"error":"invalid file name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                os.remove(target)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/file/rename':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                src = resolve_config_path(body.get('from', ''))
                dst = resolve_config_path(body.get('to', ''))
                if not src or not os.path.isfile(src) or not dst:
                    resp = b'{"error":"invalid file name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                if os.path.exists(dst):
                    resp = b'{"error":"a file already exists at the destination"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/folder/create':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                target = resolve_folder_path(body.get('folder', ''))
                if not target:
                    resp = b'{"error":"invalid folder name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                if os.path.isfile(target):
                    resp = b'{"error":"a file already exists there"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                os.makedirs(target, exist_ok=True)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/folder/delete':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                folder = body.get('folder', '')
                target = resolve_folder_path(folder)
                if not target or not os.path.isdir(target):
                    resp = b'{"error":"invalid folder name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                shutil.rmtree(target)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/folder/disable':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                target = resolve_folder_path(body.get('folder', ''))
                if not target or not os.path.isdir(target) or _is_disabled_folder_name(os.path.basename(target)):
                    resp = b'{"error":"invalid folder name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                dst = os.path.join(os.path.dirname(target), '.' + os.path.basename(target) + '.disabled')
                if os.path.exists(dst):
                    resp = b'{"error":"a disabled version already exists"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                os.rename(target, dst)
                rel = os.path.relpath(dst, os.path.realpath(CONFIG_DIR)).replace(os.sep, '/')
                resp = json.dumps({'ok': True, 'folder': rel}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/folder/enable':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                folder = body.get('folder', '')
                target = resolve_folder_path(folder)
                base_name = os.path.basename(target) if target else ''
                if not target or not os.path.isdir(target) or not _is_disabled_folder_name(base_name):
                    resp = b'{"error":"invalid folder name"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                inner = base_name[1:-len('.disabled')]
                dst = os.path.join(os.path.dirname(target), inner)
                if os.path.exists(dst):
                    resp = b'{"error":"a folder already exists at the destination"}'
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                os.rename(target, dst)
                rel = os.path.relpath(dst, os.path.realpath(CONFIG_DIR)).replace(os.sep, '/')
                resp = json.dumps({'ok': True, 'folder': rel}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path == '/api/v1/terminal/restart':
            # Restarts the service directly from eznix.py's own process, independent of the
            # terminal's own shell -- so this still works even if the running shell is wedged, or
            # the panel's never been opened. systemd on Linux, launchd on macOS (kickstart -k
            # kills the running job and starts it again); nothing to restart anywhere else.
            _user = (_session(self.headers) or {}).get('user')
            if not _terminal_for(_user):
                resp = b'{"error":"terminal not enabled"}'
                self.send_response(501)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            # The module says how (a per-user unit, a launchd agent, with sudo or not); there
            # is no guessing from the platform. Run by hand there is no service to restart.
            if _OWN_TERMINAL['argv']:
                _start_own_terminal()
                resp = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            if not TERMINAL_RESTART:
                resp = b'{"error":"no terminal_restart command is configured"}'
                self.send_response(501)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            _uid = ''
            try:
                import pwd
                _uid = str(pwd.getpwnam(_user).pw_uid)
            except (KeyError, TypeError, ImportError):
                pass
            restart_cmd = [a.replace('{user}', _user or '').replace('{uid}', _uid) for a in TERMINAL_RESTART]
            try:
                result = subprocess.run(
                    restart_cmd,
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    resp = b'{"ok":true}'
                    self.send_response(200)
                else:
                    output = (result.stdout + result.stderr).strip() or 'unknown error'
                    resp = json.dumps({'error': output}).encode()
                    self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except subprocess.TimeoutExpired:
                resp = b'{"error":"timed out after 30s"}'
                self.send_response(504)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                self.send_error(500, str(e))
        elif parsed.path.startswith('/api/v1/plugin/'):
            self._plugin_route('POST', parsed)
        else:
            self.send_error(404)

    # favicon.svg/manifest.json: no more sensitive than style.css/theme-*.css, which get the same
    # pre-auth treatment just above for the same reason (the login page needs them loadable before
    # there's any session cookie at all). manifest.json needs to be public for a different, real
    # reason though, not just symmetry: a <link rel="manifest"> fetch defaults to
    # credentials: "omit" per spec (unlike an ordinary <link>/<img> fetch), so the browser's
    # request for it carries no session cookie regardless of whether the user is actually logged
    # in -- confirmed by a real report where index.html's manifest link (and the icon it
    # references) silently failed auth right after logging in, even though the tab's own favicon
    # (an ordinary, credentialed fetch) worked fine throughout.
    _PUBLIC_PATHS = {'/login.html', '/favicon.svg', '/manifest.json'}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/logout':
            # The shell belongs to the login, not to the machine: once the last session of the
            # person who was using it is gone, so is it (where that's switched on).
            _gone = _end_session(self.headers)
            if _gone is not None and TERMINAL_END_ON_LOGOUT:
                _terminal_end(_gone)
            self.send_response(303)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', 'eznix_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            self.end_headers()
            return
        if parsed.path == '/download-ca':
            if CA_FILE and os.path.exists(CA_FILE):
                with open(CA_FILE, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-pem-file')
                self.send_header('Content-Disposition', 'attachment; filename="eznix-ca.pem"')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
            return
        if parsed.path == '/style.css' or (
                parsed.path.startswith('/theme-') and parsed.path.endswith('.css')):
            # Public (pre-auth, for the login page) and worth gzipping: style.css alone runs
            # ~46KB, served fresh on every page load since WEBROOT files are no-store.
            custom = CUSTOM_THEMES.get(parsed.path[len('/theme-'):-len('.css')])
            self._serve_static_gzip(parsed.path.lstrip('/'), custom and custom['path']); return
        if parsed.path == '/manifest.json':
            self._serve_manifest(); return
        if parsed.path in self._PUBLIC_PATHS:
            super().do_GET()
            return
        if not check_auth(self.headers):
            self._deny(); return
        if (parsed.path == '/terminal' and TERMINALS and
                self.headers.get('Upgrade', '').lower() == 'websocket'):
            # A shell, and a GET like any other to the browser: see _valid_origin().
            if not _valid_origin(self.headers):
                self.send_error(403); return
            self._proxy_terminal(); return
        if parsed.path.rstrip('/') in ('', '/index.html'):
            self._serve_index(); return
        if parsed.path == '/api/v1/ping':
            # Polled periodically by initRestartWatcher() (index.html) — see this file's own
            # module docstring above for why this is polling rather than a held-open SSE
            # connection (an earlier /api/v1/ping-stream, removed). A dead session (cookie no
            # longer valid) never reaches this handler at all — check_auth()/_deny() above
            # already reject it with 401 before this branch runs, same as any other endpoint.
            data = json.dumps(_ping_payload((_session(self.headers) or {}).get('user'))).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path.startswith('/api/v1/plugin/'):
            self._plugin_route('GET', parsed); return
        if parsed.path == '/api/v1/files':
            try:
                data = json.dumps({
                    'files': list_config_files(),
                    'folders': list_config_folders(),
                    'default': DEFAULT_FILE,
                }).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
            return
        if parsed.path == '/api/v1/backups':
            try:
                qs = parse_qs(parsed.query)
                stem = _config_stem(qs.get('file', [None])[0])
                if stem is None:
                    self.send_error(400); return
                data = json.dumps({'backups': list_backups(stem)}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
            return
        if parsed.path == '/api/v1/backup/content':
            qs = parse_qs(parsed.query)
            target = resolve_backup_path(qs.get('name', [''])[0])
            if not target:
                self.send_error(400); return
            self._serve_raw(target); return
        # A resolved config file's content and custom-options.json live in CONFIG_DIR, not WEBROOT
        if parsed.path == '/api/v1/file':
            qs = parse_qs(parsed.query)
            target = resolve_config_path(qs.get('file', [None])[0])
            if not target:
                self.send_error(400); return
            self._serve_raw(target); return
        if parsed.path == '/custom-options.json':
            self._serve_raw(os.path.join(CONFIG_DIR, 'custom-options.json')); return
        # autocomplete files: AUTOCOMPLETE_DIR when set, else WEBROOT/autocomplete/ (same default
        # as eznix-autocomplete' own default out_dir) — served via _serve_autocomplete() for conditional GET
        # + gzip, since options.json/packages.json can run into several MB on a large flake
        if parsed.path.startswith('/terminal-panel/') and TERMINALS:
            # xterm.js alone is ~490KB: worth gzipping.
            rel = os.path.normpath(parsed.path).lstrip('/')
            if not rel.startswith('terminal-panel/'):
                self.send_error(404); return
            self._serve_static_gzip(rel); return
        if parsed.path.startswith('/plugins/'):
            name, _, rel = parsed.path[len('/plugins/'):].partition('/')
            # Only what the plugin lists for the page, not its server code.
            rel = urllib.parse.unquote(rel)
            listed = name in PLUGINS and not rel.endswith(('.py', 'plugin.json'))
            path = listed and _plugin_file(PLUGINS[name]['dir'], rel)
            if not path:
                self.send_error(404); return
            self._serve_static_gzip(None, path); return
        if parsed.path.startswith('/autocomplete/'):
            rel = os.path.normpath(parsed.path[len('/autocomplete/'):]).lstrip('/')
            base = AUTOCOMPLETE_DIR or os.path.join(WEBROOT, 'autocomplete')
            self._serve_autocomplete(os.path.join(base, rel)); return
        super().do_GET()

    def do_HEAD(self):
        if not check_auth(self.headers):
            self._deny(); return
        super().do_HEAD()

    def _serve_raw(self, path):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)
        except Exception as e:
            self.send_error(500, str(e))

    def _serve_autocomplete(self, path):
        """Conditional-GET + gzip serving for /autocomplete/*.json. Unlike _serve_raw() (always
        no-store, see end_headers()), these files get real caching: options.json alone can be
        several MB on a large flake, re-downloaded on every page load/reload otherwise, and their
        mtime is genuinely meaningful (they're rewritten by eznix-autocomplete, not Nix-store
        artifacts with a frozen mtime)."""
        try:
            mtime = int(os.stat(path).st_mtime)
        except OSError:
            self.send_error(404); return
        last_modified = self.date_time_string(mtime)
        ims = self.headers.get('If-Modified-Since')
        if ims:
            try:
                ims_dt = email.utils.parsedate_to_datetime(ims)
                if ims_dt.tzinfo is None:
                    ims_dt = ims_dt.replace(tzinfo=datetime.timezone.utc)
                if int(ims_dt.timestamp()) >= mtime:
                    self._no_default_cache_control = True
                    self.send_response(304)
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Last-Modified', last_modified)
                    self.end_headers()
                    return
            except (TypeError, ValueError, OverflowError):
                pass
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            self.send_error(404); return
        gzipped = 'gzip' in self.headers.get('Accept-Encoding', '')
        if gzipped:
            data = gzip.compress(data)
        self._no_default_cache_control = True
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Last-Modified', last_modified)
        if gzipped:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_manifest(self):
        """manifest.json with this machine's name in the app's name, so a browser's "Install page
        as app" makes "eznix (hostname)" rather than one more identical "eznix". Everything
        else comes from the file in WEBROOT as it is."""
        try:
            with open(os.path.join(WEBROOT, 'manifest.json'), encoding='utf-8') as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            self.send_error(404); return
        manifest['name'] = manifest['short_name'] = f'eznix ({HOSTNAME})'
        data = json.dumps(manifest).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/manifest+json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _plugin_route(self, method, parsed):
        """/api/v1/plugin/NAME/PATH: hand the request to what that plugin registered (see
        PluginApi). Only reached once check_auth() has passed."""
        name, _, path = parsed.path[len('/api/v1/plugin/'):].partition('/')
        handler = PLUGINS.get(name, {}).get('routes', {}).get((method, path.strip('/')))
        if not handler:
            self.send_error(404); return
        status, headers = 200, {'Content-Type': 'application/json'}
        try:
            body = self.rfile.read(int(self.headers.get('Content-Length', 0))) if method == 'POST' else b''
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            result = handler(PluginRequest(query, body, (_session(self.headers) or {}).get('user')))
            if isinstance(result, PluginDownload):
                data = result.data
                headers = {'Content-Type': result.content_type,
                           'Content-Disposition': f'attachment; filename="{result.filename}"'}
            else:
                data = json.dumps(result).encode()
        except PluginError as e:
            status, data = e.status, json.dumps({'error': e.message}).encode()
        except Exception as e:
            print(f'eznix: plugin {name}, {method} {path}: {type(e).__name__}: {e}', file=sys.stderr)
            status, data = 500, json.dumps({'error': str(e)}).encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static_gzip(self, rel_path, abs_path=None):
        """Gzip-capable serving for a handful of sizeable static WEBROOT files (style.css,
        theme-*.css, plugin files) that don't go through SimpleHTTPRequestHandler's own static
        serving, which has no compression at all. Cache-Control stays no-store (see
        end_headers()) — these files really can change across a restart, unlike /autocomplete/*'s
        genuinely-fresh mtimes, so no attempt at conditional-GET caching here, just compression.
        _STATIC_GZIP_CACHE holds both encodings per path, built on first request. abs_path
        serves that file instead of WEBROOT/rel_path — a user theme or a plugin's file."""
        path = abs_path or os.path.join(WEBROOT, rel_path)
        cached = _STATIC_GZIP_CACHE.get(path)
        if cached is None:
            try:
                with open(path, 'rb') as f:
                    raw = f.read()
            except OSError:
                self.send_error(404); return
            cached = (raw, gzip.compress(raw))
            _STATIC_GZIP_CACHE[path] = cached
        raw, gzipped_data = cached
        use_gzip = 'gzip' in self.headers.get('Accept-Encoding', '')
        data = gzipped_data if use_gzip else raw
        self.send_response(200)
        self.send_header('Content-Type', self.guess_type(path))
        if use_gzip:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_index(self):
        try:
            # Constant for the life of this process, so rendered once. '__index__' is not a
            # real path: this is templated, not read verbatim from disk.
            cached = _STATIC_GZIP_CACHE.get('__index__')
            if cached is None:
                raw = _render_index().replace('%%EZNIX_PAGE_HASH%%', PAGE_HASH).encode('utf-8')
                cached = (raw, gzip.compress(raw))
                _STATIC_GZIP_CACHE['__index__'] = cached
            raw, gzipped_data = cached
            use_gzip = 'gzip' in self.headers.get('Accept-Encoding', '')
            data = gzipped_data if use_gzip else raw
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            if use_gzip:
                self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(len(data)))
            _cookie = _renew_session(self.headers)
            if _cookie:
                self.send_header('Set-Cookie', _cookie)
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)
        except Exception as e:
            self.send_error(500, str(e))

    def _proxy_terminal(self):
        """Relay a /terminal WebSocket upgrade straight through to eznix-terminal.py's own listener on
        127.0.0.1:the terminal's port (which only ever binds to loopback -- see eznix-terminal.py's own
        BIND_ADDR), so the browser only ever needs to trust *this* process's certificate. A
        separate wss://host:the terminal's port connection straight to eznix-terminal.py would be a different
        origin (port included), needing its own certificate-trust decision the browser has no way
        to prompt for over a raw WebSocket handshake -- see the comment on the terminal's port in
        index.html. Both legs of this relay stay plain HTTP: browser<->eznix.py is whatever
        scheme this process itself is running (TLS-wrapped already if HTTPS is on, by the time
        request handling reaches here), and eznix.py<->eznix-terminal.py never leaves the loopback
        interface, so there's nothing to encrypt on that leg regardless.

        This never parses WebSocket frames -- it's a pure byte relay, so PTY resize/reattach/
        persistence/etc. in eznix-terminal.py are completely unaffected by going through it."""
        self.close_connection = True
        term = _terminal_for((_session(self.headers) or {}).get('user'))
        if not term:
            self.send_error(404, 'no terminal for this login')
            return
        try:
            backend = socket.create_connection(('127.0.0.1', term['port']), timeout=10)
        except OSError as e:
            self.send_error(502, f'terminal backend unreachable: {e}')
            return
        try:
            headers = dict(self.headers.items())
            # eznix-terminal.py knows nothing of login sessions: this request got here because its
            # own cookie checked out (check_auth, in do_GET), and what vouches for it from here
            # on is the secret the two processes share.
            for k in [k for k in headers if k.lower() == 'cookie']:
                del headers[k]
            headers['Cookie'] = f'eznix_session={term["key"]}'
            headers['Host'] = f'127.0.0.1:{term["port"]}'
            lines = [f'{self.command} {self.path} {self.request_version}']
            lines += [f'{k}: {v}' for k, v in headers.items()]
            lines += ['', '']
            backend.sendall('\r\n'.join(lines).encode('iso-8859-1'))
            # Deliberately not checking self.rfile for leftover buffered bytes past the request
            # headers here: a real WS client sends nothing more until it gets the 101 response, so
            # self.rfile's buffer is genuinely empty at this point -- and io.BufferedReader.peek()
            # performs a real (blocking) read on the raw stream when its buffer is empty, so
            # calling it here would stall the whole proxy waiting for client bytes that were never
            # coming (confirmed: this was tried first and hung every connection).
            header_bytes, leftover_from_backend = _recv_until_double_crlf(backend)
            if not header_bytes:
                self.send_error(502, 'terminal backend closed the connection')
                return
            backend.settimeout(None)
            self.connection.sendall(header_bytes)
            if leftover_from_backend:
                self.connection.sendall(leftover_from_backend)
            t = threading.Thread(target=_pipe, args=(backend, self.connection), daemon=True)
            t.start()
            _pipe(self.connection, backend)
            t.join(timeout=2)
        finally:
            try:
                backend.close()
            except OSError:
                pass

    def log_message(self, fmt, *args):
        print(f'[web]  {self.address_string()} - {fmt % args}')


def _valid_host(headers):
    # '*' in trusted_hosts disables this check entirely — accepts any Host header. Meant for
    # cases where the reachable address genuinely can't be known ahead of time (e.g. a NixOS
    # installer ISO getting a DHCP lease), where listing exact hosts isn't possible.
    if '*' in TRUSTED_HOSTS:
        return True
    host = headers.get('Host', '').split(':')[0].lower()
    return host in {'localhost', '127.0.0.1', ''} | TRUSTED_HOSTS


def _valid_origin(headers):
    """Did this request come from the page this server served? Asked before anything that
    changes something or opens the terminal.

    The session cookie is SameSite=Strict, which keeps other *sites* from sending it -- but a
    site is a host name without its port, so a page from another port of this host (some other
    program's web interface on 127.0.0.1, say) is the same site, gets the cookie sent along,
    and could open /terminal or save a file with it. Its Origin gives it away: a browser always
    sends one with a WebSocket handshake and with a POST, and a page cannot set it.

    The Origin has to name the address the request itself was sent to (Host), port included.
    Not the scheme: behind a proxy that ends TLS the page is https and this server is not.
    Comparing against the host names in `hosts` instead would not do: the modules put every
    name the certificate is for in there, so any port of the very host this protects would
    pass. A proxy that hands on another Host than the browser's is the one case where the two
    differ, and for it `hosts` may hold the page's whole origin ("https://nix.example.org").

    No Origin at all is let through: that is curl or a script, which need no page to trick."""
    origin = headers.get('Origin')
    if origin is None or '*' in TRUSTED_HOSTS:
        return True
    origin = origin.strip().lower().rstrip('/')
    if origin.partition('://')[2] == headers.get('Host', '').strip().lower() != '':
        return True
    return origin in {h.lower().rstrip('/') for h in TRUSTED_HOSTS if '://' in h}


def _start_terminal_for_self(cfg):
    """Run by hand: start our own eznix-terminal, as a child, for whoever is running this.
    The key is written before the child starts, so there is never a moment where the two
    disagree about it."""
    key_file = os.path.join(STATE_DIR, 'terminal.key')
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_hex(32))
    port = int(cfg.get('terminal_port') or WEB_PORT + 1)
    TERMINALS['*'] = {'port': port, 'key_file': key_file, 'dir': FLAKE_DIR, 'shell': cfg.get('shell')}
    argv = [sys.executable, TERMINAL_SCRIPT, '--port', str(port), '--key-file', key_file, '--dir', FLAKE_DIR]
    if cfg.get('shell'):
        argv += ['--shell', cfg['shell']]
    _OWN_TERMINAL['argv'] = argv
    _start_own_terminal()
    atexit.register(lambda: _OWN_TERMINAL['proc'] and _OWN_TERMINAL['proc'].terminate())
    # atexit doesn't run on a plain kill; make that an ordinary exit so the child goes too.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def main():
    global FLAKE_DIR, CONFIG_DIR, EXCLUDE, DEFAULT_FILE, STATE_DIR, AUTOCOMPLETE_DIR, WEBROOT
    global BACKUP_DIR, BACKUP_COUNT
    global BIND_ADDR, WEB_PORT, TRUSTED_HOSTS, CERT_FILE, KEY_FILE, CA_FILE, USE_TLS
    global SYSTEM_LOGIN, ALLOWED_USERS, AUTH_HELPER
    global TERMINAL_RESTART, TERMINAL_END_ON_LOGOUT, TERMINAL_SCRIPT, TERMINAL_CURRENT_HASH
    global TERMINAL_AUTO_HIDE, THEME, THEMES_DIR, CUSTOM_THEMES, EZNIX_MODE, SECTIONS_EXPANDED
    global STATIC_BUTTONS, PAGE_HASH, EZNIX_VERSION, PLUGINS, _SESSIONS_FILE

    ap = argparse.ArgumentParser(
        prog='eznix', description='A web editor for Nix configurations.',
        epilog='Everything else is set in the config file; see the top of this file.')
    ap.add_argument('--config', metavar='FILE', help='config file (default: ./eznix.toml)')
    ap.add_argument('--flake', metavar='DIR', help='the flake to edit')
    ap.add_argument('--config-dir', metavar='DIR', help='the folder of *.json files (default: <flake>/eznix)')
    ap.add_argument('--state-dir', metavar='DIR', help='where eznix keeps its own data')
    ap.add_argument('--webroot', metavar='DIR', help="the page's files")
    ap.add_argument('--listen', metavar='ADDR', help='address to listen on (default 127.0.0.1)')
    ap.add_argument('--port', type=int, help='port to listen on (default 9090)')
    ap.add_argument('--password', metavar='PW', help='log in with this password, as whoever runs eznix')
    ap.add_argument('--no-terminal', action='store_true', help="don't start or offer a terminal")
    ap.add_argument('--generate-ca', metavar='DIR',
                    help='make a local CA and a server certificate in DIR, then exit')
    ap.add_argument('--san', action='append', metavar='NAME',
                    help='with --generate-ca: an extra host name or address for the certificate')
    args = ap.parse_args()

    if args.generate_ca:
        if not _CRYPTO:
            sys.exit('eznix: --generate-ca needs the cryptography package')
        ca_dir = os.path.abspath(args.generate_ca)
        ca_new, srv_new = generate_local_ca(ca_dir, extra_sans=list(args.san or []))
        print(f'ca   → {os.path.join(ca_dir, "ca.pem")}' + (' (new)' if ca_new else ''))
        print(f'cert → {os.path.join(ca_dir, "localhost.pem")}'
              + (' (new)' if srv_new else ' (unchanged)'))
        return

    cfg = load_toml(args.config) if args.config else (
        load_toml('eznix.toml') if os.path.exists('eznix.toml') else {})
    path = lambda p: os.path.abspath(os.path.expanduser(p))

    # Where things are.
    FLAKE_DIR  = path(args.flake or cfg.get('flake') or FLAKE_DIR)
    CONFIG_DIR = path(args.config_dir or cfg.get('config_dir') or os.path.join(FLAKE_DIR, 'eznix'))
    DEFAULT_FILE = cfg.get('default_file')
    EXCLUDE = [e for e in (str(x).replace('\\', '/').strip('/') for x in cfg.get('exclude', [])) if e]
    STATE_DIR  = path(args.state_dir or cfg.get('state_dir') or STATE_DIR)
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except OSError as e:
        sys.exit(f'eznix: {CONFIG_DIR}: {e}')
    AUTOCOMPLETE_DIR = path(cfg.get('autocomplete_dir') or os.path.join(STATE_DIR, 'autocomplete'))
    WEBROOT = path(args.webroot or cfg.get('webroot') or next(
        (d for d in (os.path.join(HERE, 'webroot'), os.path.join(HERE, '..', 'webroot'))
         if os.path.isdir(d)), os.path.join(HERE, 'webroot')))
    if not os.path.exists(os.path.join(WEBROOT, 'index.html')):
        sys.exit(f'eznix: no index.html in {WEBROOT} (--webroot)')
    BACKUP_DIR = os.path.join(STATE_DIR, 'backups')
    BACKUP_COUNT = int(cfg.get('backups', 5))

    # Network.
    BIND_ADDR = args.listen or cfg.get('listen') or BIND_ADDR
    WEB_PORT  = int(args.port or cfg.get('port') or WEB_PORT)
    TRUSTED_HOSTS = {str(h) for h in cfg.get('hosts', [])}
    CERT_FILE, KEY_FILE, CA_FILE = cfg.get('cert'), cfg.get('key'), cfg.get('ca')
    if bool(CERT_FILE) != bool(KEY_FILE):
        sys.exit('eznix: "cert" and "key" go together')

    # Who may log in: settled once the plugins are loaded, further down.
    AUTH_HELPER = cfg.get('auth_helper')
    if args.password:
        cfg.setdefault('plugin', {}).setdefault('password', {})['password'] = args.password

    # Sessions survive a restart.
    _SESSIONS_FILE = os.path.join(STATE_DIR, 'sessions.json')
    _load_sessions()

    # Looks.
    THEMES_DIR = cfg.get('themes_dir')
    CUSTOM_THEMES = _scan_custom_themes(THEMES_DIR)
    THEME = cfg.get('theme') or DEFAULT_THEME
    if THEME not in BUILTIN_THEMES and THEME not in AUTO_THEMES and THEME not in CUSTOM_THEMES:
        sys.exit(f'eznix: theme "{THEME}" is neither built in '
                 f'({", ".join(BUILTIN_THEMES + tuple(AUTO_THEMES))}) nor a <name>.css in themes_dir')
    EZNIX_MODE = cfg.get('mode') or None
    if EZNIX_MODE not in (None, 'install'):
        sys.exit(f'eznix: mode = "{EZNIX_MODE}": the only mode is "install"')
    SECTIONS_EXPANDED = cfg.get('sections') == 'expanded'
    TERMINAL_AUTO_HIDE = bool(cfg.get('terminal_auto_hide', True))
    STATIC_BUTTONS = [b for b in cfg.get('buttons', []) if isinstance(b, dict) and b.get('label') and b.get('command')]

    # Terminals: the ones the config names, or one of our own.
    TERMINAL_SCRIPT = cfg.get('terminal_script') or next(
        (p for p in (os.path.join(HERE, 'eznix-terminal.py'), os.path.join(HERE, 'eznix-terminal'))
         if os.path.exists(p)), None)
    TERMINAL_CURRENT_HASH = _compute_file_hash(TERMINAL_SCRIPT)
    TERMINAL_END_ON_LOGOUT = bool(cfg.get('terminal_end_on_logout', True))
    _tr = cfg.get('terminal_restart')
    TERMINAL_RESTART = [str(a) for a in _tr] if isinstance(_tr, list) and _tr else None
    want_terminal = cfg.get('terminal', True) and not args.no_terminal
    for user, t in (cfg.get('terminals') or {}).items():
        if want_terminal and isinstance(t, dict) and t.get('port') and t.get('key_file'):
            TERMINALS[str(user)] = {'port': int(t['port']), 'key_file': str(t['key_file']),
                                    'dir': t.get('dir'), 'shell': t.get('shell')}
    if want_terminal and not TERMINALS and TERMINAL_SCRIPT and os.name == 'posix':
        _start_terminal_for_self(cfg)

    EZNIX_VERSION = _read_version()
    PLUGINS = _load_plugins(cfg)

    # System passwords are the login when the config names users for it, or when no plugin
    # brought a login of its own. Never start with no way in at all.
    ALLOWED_USERS = {str(u).strip() for u in cfg.get('users', []) if str(u).strip()}
    SYSTEM_LOGIN = bool(ALLOWED_USERS) or not LOGINS
    if SYSTEM_LOGIN:
        ALLOWED_USERS = ALLOWED_USERS or {getpass.getuser()}
        if _PAM is None and not AUTH_HELPER:
            if not LOGINS:
                sys.exit('eznix: nobody could log in: no password is set, and checking system '
                         'passwords needs the python-pam package (or "auth_helper"). '
                         'Try: eznix --password SOMETHING')
            sys.exit('eznix: "users" is set, but checking system passwords needs the python-pam '
                     'package (or "auth_helper")')
    PAGE_HASH = _compute_page_hash()

    try:
        srv = http.server.ThreadingHTTPServer((BIND_ADDR, WEB_PORT), StaticHandler)
    except OSError as e:
        sys.exit(f'eznix: cannot listen on {BIND_ADDR}:{WEB_PORT}: {e}')
    if CERT_FILE:
        try:
            srv.socket = make_ssl_context().wrap_socket(srv.socket, server_side=True)
        except (OSError, ssl.SSLError) as e:
            sys.exit(f'eznix: cert/key: {e}')
        USE_TLS = True

    n = len(list_config_files())
    print(f'eznix → {"https" if USE_TLS else "http"}://localhost:{WEB_PORT}')
    print(f'flake → {FLAKE_DIR}')
    print(f'files → {CONFIG_DIR} ({n} file{"" if n == 1 else "s"})')
    print(f'state → {STATE_DIR}')
    for plugin, _check, user in LOGINS:
        print(f'login → {user or "?"}, by the {plugin} plugin')
    if SYSTEM_LOGIN:
        print(f'login → system password of: {", ".join(sorted(ALLOWED_USERS))}')
    print('terminal → ' + (', '.join(f'{"whoever logs in" if u == "*" else u} (127.0.0.1:{t["port"]})' for u, t in sorted(TERMINALS.items())) or 'none'))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
