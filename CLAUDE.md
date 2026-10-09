# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## Git

**As of 2026-10-09 work is committed to the `testing` branch, locally only**, on the user's
instruction ("only commit locally for now as i want to test things here"). `origin` is
`git@github.com:kalken/eznix.git`, which did not exist on GitHub when the remote was added;
nothing has been pushed. Don't create it until the user says so; when they do, it is to be
public. There is no `develop` or `master` yet, so the rule about them below
waits until the user sets those up.

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
(`eznix.toml`, a copy of a flake, state) -- inside it, `nix build path:.` would copy the test
state, keys included, into the Nix store.

```sh
pkill -f "eznix.py --config eznix.toml"; sleep 1
(cd ../.eznix-test && PYTHONUNBUFFERED=1 nohup python3 ../eznix/bin/eznix.py --config eznix.toml >| server.log 2>&1 &)
sleep 2; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9690/api/v1/ping   # 401 = up
```

http://127.0.0.1:9690, password `eznix`. eznix starts its own terminal there (port 9691), so
restarting the server restarts the shell too.

The test flake there is a nix-darwin configuration that takes eznix as a `path:` input. To
fill in suggestions, run in its terminal (there is a "Suggestions" button for it):
`python3 ~/Documents/projects/github/eznix/bin/eznix-autocomplete.py --flake . --output ../state/autocomplete`

The user's own Mac still runs the earlier ezconf (https://localhost:9090, flake in
`/etc/nix-darwin`); it has not been switched to eznix.

`python3 test/test_server.py` checks the server and the plugins' server halves against a
throwaway flake. Run it after touching `bin/eznix.py` or a plugin's `.py`. It does not cover
anything that happens in the page.

## Documentation

When a change adds, removes or changes what a user sees or sets, update `README.md` too
(features and usage, for users), not only this file (how the code is put together, for the
next session). `example/eznix.example.toml` lists every setting.

Most of the *why* lives in comments next to the code it explains, on purpose: many of them
record an approach that was tried and reverted, and what broke. Read them before changing the
thing they sit on, and keep them when moving code.

## What this is

A web editor for Nix configuration: NixOS, nix-darwin and standalone home-manager. It edits
`*.json` files in one folder inside the user's flake (`config_dir`, default `<flake>/eznix`),
each file a tab, merged at evaluation time by `nix/json2nix.nix` (installed there as
`default.nix`). No build step, no framework, no dependencies beyond Python's standard library
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
| `test/test_server.py` | server tests |

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

**A terminal is never restarted by a rebuild.** It forks the shell as its own child, so a
restart kills what runs there, most likely the rebuild itself. NixOS: `restartIfChanged =
false`. home-manager: `X-SwitchMethod = keep-old`. nix-darwin has no such switch and reloads a
job whenever its definition changes, so the terminal's job contains no store path at all and
runs `/run/current-system/sw/bin/eznix-terminal`. Don't put anything that varies per build into
that job. The page instead offers a restart when the running terminal differs from the
current one: two hashes, of the program (`SELF_HASH`) and of how it was started
(`CONFIG_HASH`, over port/key file/dir/shell; `_terminal_for()` in the server computes the
same thing from `[terminals.NAME]`, so those must be exactly the arguments the module passes).

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

**Sessions**: a random token per login in the `eznix_session` cookie (400 days, renewed on
every page load), stored hashed in `<state>/sessions.json`, so neither a restart nor quitting
the browser logs anyone out.

**Login**: system passwords are built in (`users`; PAM in-process, or `auth_helper`). Any other
way is a plugin calling `api.login(check, user)`; the shipped `password` plugin is the one
configured password. System login is on when `users` is set or no plugin brought a login, and
eznix refuses to start if nobody could log in.

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
  `render`, `dirty`, `theme`, `ping`), `eznix.addButton()` and `eznix.addMenuItem()`. All of
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

HTTPS: off on localhost; `generateCert` (on by default when `listen` isn't local) makes a local
CA and certificate in the state folder. Nothing installs the CA into browsers or the keychain
automatically; the README gives the command.

Suggestions are never generated automatically and no button for it is added: it is the
`eznix-autocomplete` command, run by the user.

## Not verified

- The terminal panel, the Documents button and the Import/Export/Restore buttons have not been
  opened in a browser since their code moved out of `index.html`.
- The NixOS and home-manager modules are evaluated only (NixOS to a full system derivation);
  nothing has run on a real machine. The setuid helper and per-user terminal units in
  particular are from how systemd and PAM behave, not from a run.
- The nix-darwin module builds, and the built editor and terminal were run by hand with its
  generated config (hashes match, proxy works), but it has not been activated.
- System-password login on a non-NixOS Linux through nixpkgs' PAM library.
