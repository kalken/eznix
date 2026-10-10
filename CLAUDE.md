# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## Git

Work is committed to `develop`, made from `testing` on 2026-10-09 when the user judged it
stable enough (`origin` is `github.com/kalken/eznix`, public). There is no `master` yet.

Nothing about one person's machine belongs in this file (their paths, their flake, what
their computer runs): it is checked in and public.

Do not add Claude as co-author in commit messages.

Do not push unless the user explicitly says so in that turn. Committing is not a go-ahead to push.

All changes go to `develop` first. Only merge `develop` into `master`; never commit to `master`.

## Workflow

Don't use subagents for work in this repo. Don't test changes in a real browser (headless
Chrome, CDP, etc.) unless the user explicitly asks for it in that turn.

**Local test server**: after any change the user can see (anything under `webroot/`, or
`bin/eznix.py`), restart it before reporting back, without being asked. The server renders the
page once at start, so an edit shows nothing until it restarts; an open tab then reloads by
itself (see "Page checksum"). Its data lives *outside* the checkout, in `../.eznix-test/`
(`eznix.toml`, state, and usually a flake to edit; what `eznix.toml` points at can differ
from one machine to the next, so read it instead of assuming) -- inside it, `nix build path:.` would copy the test
state, keys included, into the Nix store.

```sh
pkill -f "eznix.py --config eznix.toml"; sleep 1
(cd ../.eznix-test && PYTHONUNBUFFERED=1 nohup python3 ../eznix/bin/eznix.py --config eznix.toml >| server.log 2>&1 &)
sleep 2; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9690/api/v1/ping   # 401 = up
```

http://127.0.0.1:9690, password `eznix`. eznix starts its own terminal there (port 9691), so
restarting the server restarts the shell too.

To fill in suggestions, press Autocomplete in the header: run from a checkout it types
`python3 .../bin/eznix-autocomplete.py --flake FLAKE --output STATE/autocomplete` into the
terminal (`_autocomplete_command()`).

Nothing tests the page's own scripts. Without `node`, a Mac can still parse them, and run a
function lifted out of them: `osascript -l JavaScript file.js` (wrap a script in
`new Function(source)` to check its syntax without running it; don't name a function `run`,
which that runner calls by itself). Do at least the syntax check after editing page code.

`python3 test/test_server.py` checks the server and the plugins' server halves against a
throwaway flake. Run it after touching `bin/eznix.py` or a plugin's `.py`. It does not cover
anything that happens in the page.

## Documentation

When a change adds, removes or changes what a user sees or sets, update `REFERENCE.md` too
(features and usage, for users), not only this file (how the code is put together, for the
next session). `example/eznix.example.toml` lists every setting.

`README.md` is kept short on purpose, for people who don't know Nix: what it is, three
blocks of lines to copy for installing, four steps for using it, a pointer to
`REFERENCE.md`. The user asked for that twice ("for people who dont know much", "its too
much text"). Don't grow it: new material goes in `REFERENCE.md`.

Most of the *why* lives in comments next to the code it explains, on purpose: many of them
record an approach that was tried and reverted, and what broke. Read them before changing the
thing they sit on, and keep them when moving code.

## What this is

A web editor for Nix configuration: NixOS, nix-darwin and standalone home-manager. It edits
`*.json` files in one folder inside the user's flake (`config_dir`, default `<flake>/eznix`),
each file a tab, merged at evaluation time by `nix/json2nix.nix`, which the user's flake
imports as `eznix.lib.jsonDir ./eznix`. No build step, no framework, no dependencies beyond Python's standard library
(`python-pam` for system-password login and `cryptography` for `--generate-ca` are optional).

It is a from-scratch rewrite of an earlier project, ezconf, which ran as root. Nothing here
runs as root, and there is no compatibility with ezconf's configuration.

| | |
|---|---|
| `bin/eznix.py` | the server, one file: static files, the API, logins, the terminal proxy, plugin loading |
| `bin/eznix-terminal.py` | the terminal: a PTY behind a WebSocket, a separate process per user |
| `bin/eznix-autocomplete.py` | generates the suggestions (`nix eval` over the flake) |
| `webroot/index.html`, `style.css` | the page: one script, no modules |
| `webroot/theme-*.css` | themes: variables only (see `THEMES.md`) |
| `webroot/terminal-panel/` | the terminal's part of the page, with xterm.js |
| `webroot/plugins/NAME/` | the shipped plugins: `documents`, `system`, `password` |
| `nix/` | packages, the options shared by the modules, one module per system |
| `templates/` | a starting flake per system, for `nix flake init -t` (see `templates` in `flake.nix`) |
| `test/test_server.py` | server tests |
| `test/json/` | a folder for `checks.json-dir` (`nix flake check --no-build`) |

## Design decisions worth knowing

**Nothing is root.** The editor is reachable from a browser, so it runs unprivileged
everywhere; a rebuild goes through `sudo` in the terminal. On NixOS the two things an
unprivileged service can't do are given to it narrowly: a setuid helper that only checks a
password for the listed users (`auth_helper`), and a sudo rule that only restarts the terminal
units (`terminal_restart`).

**A terminal is a separate process, per user, on 127.0.0.1.** The browser never connects to
it: `_proxy_terminal()` relays `/terminal` after its own login check, replacing the browser's
cookie with that terminal's own secret (`key_file`). Each user's terminal has its own secret,
or the allowed users could reach each other's shells over loopback. The terminal never creates
the secret; whoever starts it does, before it starts.

**A page that reconnects gets the terminal's history back**, up to 5000 lines: the terminal
keeps each line that scrolls off the top of its record of the screen (`_VirtualScreen`,
`_scrollback`), already rendered as text with its colours, and sends them ahead of the screen
itself. The user needed it for rebuilds: one that updates eznix restarts the editor, the page
reloads, and the rebuild's earlier output was out of reach. It is not the replay of raw output
that was given up before (the comment above the class says why); nothing in those lines is
interpreted again. Not kept: what a full-screen program showed.

**A terminal is never restarted by a rebuild.** It forks the shell as its own child, so a
restart kills what runs there, most likely the rebuild itself. NixOS: `restartIfChanged =
false`. home-manager: `X-SwitchMethod = keep-old`. nix-darwin has no such switch and reloads a
job whenever its definition changes, so the terminal's job contains no store path at all and
runs `/run/current-system/sw/bin/eznix-terminal`. Don't put anything that varies per build into
that job. The page instead offers a restart when the running terminal differs from the
current one. A terminal has one checksum (`STAMP`) over its program file and how it was
started (port/key file/dir/shell); `_terminal_for()` in the server computes the same thing
from the installed program and `[terminals.NAME]`, so those must be exactly the arguments
the module passes. The server compares the two (`_terminal_stale()`) and the ping carries
only the answer, `terminal_stale`; the page compares nothing. It was four values in the ping
and two ways of learning them until 2026-10; don't grow it back. The terminal's package has
no version in its name (`packages.nix`), or its store path, and with it the unit NixOS
watches, would change with every commit.

**Run by hand, eznix starts its own terminal** as a child (`_start_terminal_for_self()`),
writing the key first, registered for whoever logs in (`TERMINALS['*']`).

**Page checksum** (`_compute_page_hash()`, `PAGE_HASH`): one hash of the rendered page (so
every setting in it), every file under `webroot/`, user themes and plugins, and `eznix.py`.
The page is built with the value and `/api/v1/ping` reports the current one; a page seeing
another reloads, at once if nothing is unsaved, otherwise as soon as that is true
(`_updateDirty()`). There is no field-by-field comparison to keep up to date. Autocomplete
data is left out of it (it changes while the server runs) and has its own stamp in the ping.
Polling, not `EventSource`: one reconnecting after a restart wiped Chromium's cookies for the
origin.

**Sessions**: a random token per login in the `eznix_session` cookie, stored hashed in
`<state>/sessions.json`, so a restart of the server logs nobody out. How long the cookie
lasts is set under `[session.cookies]` (`session.cookies.*` in the modules). `days` unset, which is the default the user chose, it has no lifetime and
the browser drops it when it quits; set, it lasts that many days from the login, 400 at most
because browsers cap cookies there. `renew` counts them from the last page load
instead, which the user wanted as a separate, explicit choice. It used to be fixed at 400
days and always renewed.

**Requests must come from the page** (`_valid_origin()`): every POST but the login itself and the
`/terminal` handshake are refused when the `Origin` header names another address than the `Host` the
request was sent to, port included. The cookie's `SameSite=Strict` does not cover this, since
a page on another port of the same host counts as the same site. `hosts` is deliberately not
used for it, except for an entry that is a whole origin (`"https://name"`, for a proxy that
changes `Host`): the modules put the certificate's names in `hosts`, so matching host names
would let any port of the protected host through. `/logout` is a GET and is not
checked: a page on another port of the host could log the user out, which also ends their
shell (`terminal_end_on_logout`). Any other GET that changes something would need the check.

**`interface`** ties the listening socket itself to one network interface
(`_bind_to_interface()`: `SO_BINDTODEVICE` on Linux, `IP_BOUND_IF` on macOS), because the
user wanted that as a setting of eznix and not a firewall rule beside it. It shuts out the
machine itself too (local traffic arrives through loopback). On NixOS `openFirewall` then
opens the port on that interface only.

**With `interface` or `listen = "0.0.0.0"` the names go in `certNames`, by hand.** eznix
doesn't know what will be typed in the browser, so the certificate names only localhost and
a save to any other name is refused until it is listed. Looking the machine's addresses up
(an ioctl per request, and again for the certificate at start) was built and taken out
again on 2026-10-09: the user found it hacky and prefers a certificate that is plainly wrong
until `certNames` is set, with the options' descriptions saying so. Those descriptions are
what the editor shows as a setting's help, so they are the documentation that matters here.

**Login**: system passwords are built in (`users`; PAM in-process, or `auth_helper`). Any other
way is a plugin calling `api.login(check, user)`; the shipped `password` plugin is the one
configured password. System login is on when `users` is set or no plugin brought a login, and
eznix refuses to start if nobody could log in.

**eznix installs nothing in the folder it edits.** `json2nix.nix` used to be copied there as
`default.nix` (`imports = [ ./eznix ]`); the user chose the function instead
(`lib.jsonDir DIR`, or `{ dir, exclude }`), so the folder can be one with a `default.nix` and
other JSON of its own, the flake's root included. `exclude` exists twice and the two must
agree: the function's argument keeps a path out of the build, the editor's setting
(`_excluded()`) keeps it from being a tab. A module can't pass its option to the function
(what the function reads decides `config`, so reading `config` there recurses). A raw
expression is another matter and gets every argument the module does (`config`, `options`,
`specialArgs` such as `inputs`, beside `pkgs` and `lib`): it is a value, evaluated when asked
for, like one in any module. Raw
expressions (`_expr`) go through `builtins.toFile`, which fails under `nix flake check`'s
read-only evaluation ("path ... expr.nix is not valid"); a rebuild is unaffected. That is as
old as the feature. `checks.json-dir` covers the function, without `_expr` for that reason.

**Templates** (`templates/darwin`, `nixos`, `home`): a `flake.nix` and one JSON file with
eznix on. The configuration is named `default` in each, on the user's wish to keep the host
name out of the flake, so every rebuild command in them carries `#default`. The NixOS one
imports the installer's `configuration.nix` and adds eznix beside it: starting from an empty
JSON file would drop the boot loader and the user's account. The macOS one sets `nix.enable = false`: the user runs
Determinate Nix, under which nix-darwin aborts activation unless that is set, and it is
harmless with the official installer. The one thing to fill in is
`YOUR-USER-NAME`; an assertion in `options.nix` catches it left in. They name
`github:kalken/eznix`, so they are only as new as what is pushed; to try one against the
checkout, `--override-input eznix path:.`.

**A system import is all or nothing** (`prepare()` in the system plugin): what it would write
or remove is worked out first, files already identical are left alone, and if eznix may not
change any one of the rest, it refuses before the snapshot and before the first write. On
NixOS with `flakeWritable = false` the service can write only its JSON folder, and an import
used to write what it could there and then fail on `flake.nix`.

**On NixOS the whole flake is group-writable for `eznix` by default** (`flakeWritable`, in
`nixos.nix`), because the user needs the system import to work there. Group and mode only:
the owner of each file is left alone, since git and Nix refuse a repository owned by someone
else, and dot-folders are skipped for the same reason. It gives the service nothing it
didn't have: a JSON file it could already write can hold any Nix expression, built as root
at the next rebuild.

**Nothing touches disk until Save**, including deletes, renames and moves (`pendingFsOps`,
replayed in order). Undo is one global stack of full-state snapshots and survives a reload.

## Plugins

**A plugin is something that needs nothing from the system eznix runs on.** That is the rule
the user settled on, after the terminal had briefly been one: making it a complete plugin
would have needed several new hooks and a Nix half per system, for a feature nobody wants to
replace. So the terminal is part of eznix (its server side in `eznix.py`, its services in the
Nix modules, its options at the top level), and only its page code lives apart, in
`webroot/terminal-panel/`: loaded like a plugin's files when a terminal is set up
(`TERMINAL_PANEL`), and reached by the page through the same events, so the page still never
names anything in it. Don't turn features that need a service into plugins.

A plugin is a folder with a `plugin.json`: `{"name", "styles": [], "scripts": [], "server":
"x.py"}`, all but the name optional. Found in `webroot/plugins/` and in `plugins_dir`
(`_load_plugins()`); `[plugin.NAME]` in the config holds its settings, `enabled = false`
leaves it out. Nobody outside eznix depends on the interface yet, and the README says it may
change, so it can be reshaped freely.

- **Page side**: its scripts are loaded after the page's own script and before `_init()` runs.
  They share the page's global scope, which is what let existing code move out unchanged; the
  page itself only ever reaches a plugin through `eznix.emit()` events (`init`, `ready`,
  `render`, `dirty`, `theme`, `ping`), and `eznix.addButton()`. All of
  it is documented at the top of the main script, under "Plugins". The page must never name a
  plugin's function directly, or it breaks when that plugin is left out.
- **Server side**: `setup(api)` in the server file registers handlers under
  `/api/v1/plugin/NAME/` (`PluginApi`: `api.get/post`, `api.config`, `api.flake`,
  `api.state_dir`, `api.page`, `api.login`). A handler returns JSON-able data or an
  `api.Download`, and raises `api.Error(status, message)`. Core checks the login first. A
  plugin whose server file fails to load is left out whole.
- `.py` files and `plugin.json` are not served to the browser.

Core, not plugins, by decision: the terminal, Save, ordinary import/export of files, file backups on save,
themes (a theme stays a plain CSS file anyone can install without trusting code), and support
for each system (that is the Nix modules' job, before the server ever runs).

## Nix

`nix/options.nix` holds the options and builds `eznix.toml` from them with `pkgs.formats.toml`;
each module (`nixos.nix`, `darwin.nix`, `home.nix`) passes it its own paths and adds only the
services. NixOS is the service design (account `eznix`, a terminal unit per user in `users`).
macOS and home-manager are for one person: two agents/user units running as them.

HTTPS is one switch, `enableHttps`: on by default when `listen` isn't local or a `cert` is
given, and settable for localhost. With no `cert`/`key`, eznix makes a local CA and
certificate in the state folder (`generateCert`, now internal to `options.nix`). It was an
option called `generateCert` until 2026-10-09; the user found "enable HTTPS" the natural
name, and the old one is kept as a renamed option in each module. Nothing installs the CA
into browsers or the keychain unless `trustCert` is set; the reference gives the command.

With a certificate, plain HTTP on the same port gets a redirect to https (`_Server`,
`_redirect_to_https()`): the first byte of a connection says which it is. The TLS handshake
moved from the listening socket into each connection's thread for that, which also stops a
silent client from holding up `accept()`. Not in `test_server.py`, which has no
`cryptography` to make a certificate with; tried by hand with `nix run . -- --https`.

`trustCert` (off by default, as the user asked) adds that authority to the browsers of the
machine eznix runs on: `trustCertScript` in `options.nix`, ported from ezconf's
`installCerts`, which ran as root for a list of users and was on by default. Here it always
runs as the person concerned: a oneshot unit per user on NixOS, the editor's `ExecStartPre`
under home-manager, `sudo -u` in the activation on macOS, where the keychain part needs the
password dialog a rebuild in a real terminal can show. Read the comments there before
touching it; each oddity was found on a real machine.

Suggestions are never generated automatically: it is the `eznix-autocomplete` command, run by
the user. Since 2026-10-10 the header has an Autocomplete button for it, on the user's wish,
which only types that command into the terminal (it is part of `terminal-panel/`, so there is
none without a terminal); before that the templates carried it as one of their buttons.
Its icon turns while the generator runs: the generator leaves `.generating`, with its
process number, where the suggestions go, and the ping says whether that process is there
(`_autocomplete_running()`). Whether the suggestions are *behind* the flake is not shown: a
checksum of `flake.nix` and `flake.lock` was built for it and dropped the same day, since it
misses a module added in any other file, and the user chose a button that is always active.

## Not verified

What has run for real, by the user's reports on 2026-10-09 and no closer than that: all three
modules. nix-darwin on a Mac (services, system-password login, the terminal surviving
rebuilds, HTTPS on localhost with `trustCert` and its keychain dialog, the redirect from
http); NixOS on a real machine ("works cleanly", including `interface` once `certNames` was
set); home-manager on another Linux in a VM, where the terminal's missing environment and
`home.packages` not being a package list were found and fixed. The terminal restart notice
was seen on NixOS and macOS across an update that changed the terminal. The user tested
"all I could" and it works on the three; the points below are what nobody went through.

- `trustCert` on NixOS (the per-user units). The home-manager step was tried by the user on
  Debian; on macOS it is confirmed.
- `flakeWritable` on NixOS, as something that works: a listing the user sent shows the
  permissions it sets (the flake and its files `root:eznix` and group-writable with the
  owner unchanged, setgid and ACL on the folders, `.git`, another dot-folder and
  `.gitignore` untouched), but the user has not tried writing the flake through the editor,
  and no system import has been done there.
- The `darwin` and `nixos` templates on a machine that had nothing. (`home` was: on a fresh
  Debian 13 VM, `nix flake init -t`, the name filled in, the password file, the first
  switch, and it worked first time.)
- The Documents button and the System menu (Export, Import, Backup, the backups to restore): never opened in
  a browser by a session, neither when their code moved out of `index.html` nor when the four
  header buttons became that one menu and Documents moved to the header (2026-10-10).
- System-password login on a non-NixOS Linux through nixpkgs' PAM library (the template
  there uses a password file).
- home-manager as a module inside a NixOS flake (`home-manager.users.<name>`): the generator
  has a path for its options, untried on a real flake.
