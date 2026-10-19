# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## Git

Work is committed to `develop`, made from `testing` on 2026-10-09 when the user judged it
stable enough (`origin` is `github.com/kalken/eznix`, public). `main` was made from it on
2026-10-13, when the user found it "almost ready", and is what the repository shows and
what `github:kalken/eznix` gives (the templates, the installer); `main` and not `master`,
as the user's installer has it. A machine that is to try what is not released yet names
`github:kalken/eznix/develop`.

Nothing about one person's machine belongs in this file (their paths, their flake, what
their computer runs): it is checked in and public.

Do not add Claude as co-author in commit messages.

Do not commit unless the user asks for it. Until then a change stays in the working tree,
and the report says that it is uncommitted. (The user's rule since 2026-10-13: "never to
commit without being asked".)

Do not push unless the user explicitly says so in that turn. Committing is not a go-ahead to push.

Always commit to `develop` first. Only merge `develop` into `main`; never commit to `main`.

## Workflow

Don't use subagents for work in this repo. Don't test changes in a real browser (headless
Chrome, CDP, etc.) unless the user explicitly asks for it in that turn.

**Local test server**: after any change the user can see (anything under `webroot/` or
`plugins/`, or `bin/eznix.py`), restart it before reporting back, without being asked. The server renders the
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

The `pkill` there only matches a server started with exactly that `--config`. One started
with another file keeps the port and keeps serving the old page, the new one fails to start,
and the 401 still comes back: on 2026-10-11 the user was told three times that a change was
live when it was not. If in doubt, see what holds the port (`lsof -nP -iTCP:9690
-sTCP:LISTEN`), restart that command line, and check that the served file has the change.

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

When a change adds, removes or changes what a user sees or sets, update `README.md` too
(features and usage, for users), not only this file (how the code is put together, for the
next session). `example/eznix.example.toml` lists every setting.

`README.md` is the one document for users, laid out like the user's other repositories
(ezconf, ezinstall): the name and a line on what it is, `## ✨ Features` as a short list,
`## 🚀 Quick Start`, then a section per topic with an emoji in its heading, `## 📋 Options`
and `## 📝 Notes` near the end, and a closing line in italics. Quick Start is what it takes
to get eznix installed and running, for people who don't know Nix: three blocks of lines to
copy and three steps for using it. Keep that part short ("for people who dont know much",
"its too much text"): nobody should have to read far to get going. New material goes in the
sections after it. A link to a section has the emoji's place as a hyphen (`#-https`), and
the emoji in a linked heading must be a single character with no variation selector, or the
anchor gets an invisible character in it. It was two files for a day, a short `README.md`
and a `REFERENCE.md` (2026-10-09/10); the user did not like having two and asked for one.

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
| `bin/eznix-autocomplete.py` | generates the suggestions (`nix eval` over the flake): the options and packages every system has, and what the plugins add |
| `webroot/index.html`, `style.css` | the page: one script, no modules |
| `webroot/theme-*.css` | themes: variables only (see `THEMES.md`) |
| `webroot/terminal-panel/` | the terminal's part of the page, with xterm.js |
| `plugins/NAME/` | the shipped plugins: `documents`, `files`, `system`, `password`, each with its page files, its server file and a `README.md` (they were in `webroot/plugins/` until 2026-10-12); and `kernels`, `homebrew`, `home-manager`, which hold only a generator file (see "The generator's plugins") |
| `nix/` | packages, the options shared by the modules, one module per system |
| `templates/` | a starting flake per system, for `nix flake init -t` (see `templates` in `flake.nix`) |
| `test/test_server.py` | server tests |
| `test/json/` | a folder for `checks.json-dir` (`nix flake check --no-build`) |

## Design decisions worth knowing

**General solutions, never special cases.** The user's rule for all of eznix, said again on
2026-10-11: the editor handles data it cannot know in advance (any option of any module, any
name, any nesting, any theme), and most of it is never looked at by anyone. So a fix is made
for the kind of thing, not for the one that was on screen: no code that names an option, a
section, a file or a theme, and no branch per kind of row where one rule can cover them all
(take what differs from the element itself, as the rename field inherits its font and colour
from the name it covers). If a fix only works for the case in the report, it is not done.
"The suggestions are parsed by their form" below is the same rule applied to one area.

**Nothing is root.** The editor is reachable from a browser, so it runs unprivileged
everywhere; a rebuild goes through `sudo` in the terminal. On NixOS the two things an
unprivileged service can't do are given to it narrowly: a setuid helper that only checks a
password for the listed users (`auth_helper`), and a sudo rule that only restarts the terminal
units (`terminal_restart`). The helper is a small C program (`nix/eznix-auth.c`, the users
compiled in) since 2026-10-15: it was a Python script until nixpkgs-unstable began refusing
any wrapper target that is not an ELF binary (2026-10-03), which stopped the user's rebuild
of a machine on unstable. Compiled on a Mac and evaluated into a NixOS system on unstable;
then, the same day, rebuilt on NixOS by the user and logged in with a system password
("it works"; which release the machine was on was not said).

**A terminal is a separate process, per user, on 127.0.0.1.** The browser never connects to
it: `_proxy_terminal()` relays `/terminal` after its own login check, replacing the browser's
cookie with that terminal's own secret (`key_file`). Each user's terminal has its own secret,
or the allowed users could reach each other's shells over loopback. The terminal never creates
the secret; whoever starts it does, before it starts. On NixOS the key is the user's own
(mode 600) with an ACL entry for the account `eznix` alone (`setfacl -m u:eznix:r`) since
2026-10-16: it was `user:eznix` mode 640, and every user in `users` is in the group `eznix`,
so each could read the others' keys, against what the comment there said (found when the
user asked whether every file that needs protecting was protected). Evaluated on a copy of
the NixOS template, then run by the user the same day on a NixOS machine: `getfacl` shows
`user:eznix:r--`, `group::---` and `mask::r--`, the certificate keys on that machine were
`0600` after the rebuild, and the terminal panel connected ("yes it works"). The script
stops the unit if `setfacl` fails, which is meant. The key's folder
(`/run/eznix-terminal/USER`) is root's, mode 755, since 2026-10-17, and only the key file is the
user's: the start step runs as root, and with the folder the user's they could put a symlink
where the key goes and press Restart (which runs it again), so that root ran `chmod` and
`setfacl` on whatever the link named, or made a file at its end (a dangling link). Found in a
review of the Nix modules, by reading; not tried on a machine. The step takes the folder over
before it looks at anything in it and removes a key that is not a plain file. The activation
script's `chgrp -h` and `setfacl -P` leave a link that appears after `find` alone; `chmod` has no
such switch, and a path swapped between the listing and the change is not ruled out (it gives
the group nothing it has not got: a `.nix` file it writes is built as root). Checked: the NixOS
template evaluated, the unit's script read out of its derivation and syntax-checked; not run.

**Private keys are written closed** (`_write_private()`): the CA's and the server's
certificate key are `0600` whatever the umask. The NixOS service runs with `UMask = 0002`
(its other files are shared with the group), and they were `0664` there, readable and
writable by every user in `users`, which with `trustCert` is a key that makes certificates
the other users' browsers trust. Mac and home-manager were `0600` only by their start
scripts' `umask 077`. A key made earlier is closed at the next start. In `test_server.py`
(`private_keys()`, which needs `cryptography` and says so when it is not there).
Since 2026-10-18 the certificates are written `0644` the same way (`_write_public()`), and
the backup folders (`backups/`, `system-backups/`) are `0755` with their files `0644`
(`_closed_folder()`, and in the system plugin): under that UMask they were `0664` and
`0775`, so a user in `users` could put an authority of their own in `ca.pem`, which
`trustCert` then added to the other users' browsers, or plant a backup. Found in a review,
by reading; in `test_server.py` (`private_keys()`, run with a Nix Python that has
`cryptography`, and `backups_closed()`), not on a NixOS machine. Backups made before keep
their mode until they are pruned.

**A page that reconnects gets the terminal's history back**, up to 5000 lines: the terminal
keeps each line that scrolls off the top of its record of the screen (`_VirtualScreen`,
`_scrollback`), already rendered as text with its colours, and sends them ahead of the screen
itself. The user needed it for rebuilds: one that updates eznix restarts the editor, the page
reloads, and the rebuild's earlier output was out of reach. It is not the replay of raw output
that was given up before (the comment above the class says why); nothing in those lines is
interpreted again. Not kept: what a full-screen program showed.

**The terminal program holds more than one shell**, each under a name (`_SESSIONS`,
`/terminal?session=NAME`, at most eight), since 2026-10-12; the one without a name is the
panel's and was the only one. Same port, key and service, so nothing changed in the
modules. The user asked "why cant we open more terminals on the same port?" after I had
said a second terminal would need the whole setup doubled, which was wrong: only the
program was written for one. A page asks for a terminal of its own with
`eznix.emit('terminal', { el, session, run, onExit })` (`_extraTerminal()` in
`terminal-panel/terminal.js`); `run` is what a new named shell is started on (`$SHELL -l -i -c`, in the
address as `run=`, with the size of its place as `rows=` and `cols=`), and nothing when
the session is already there; it was typed into a waiting shell at first, and the prompt
flashed by before the program took the screen. Closing it ends a named shell (the `end`
message), never the panel's. Tried with a small WebSocket client through the test server: two names
are two shells, coming back to a name is the same shell, `end` ends a named one and leaves
the panel's alone. The terminal in the page was not looked at.

**The terminal panel comes up in front of the editor and takes no room from it**
(`.terminal-slot` in `terminal-panel/`, `--covered-below` in `style.css`), since 2026-10-13:
its place in the page is its row of buttons and the panel grows upwards out of that. Before,
the editor shrank and grew with it, and with the panel hiding on a click outside it a click
in the editor resized the editor under the pointer; the user reported the page scrolling
"sometimes" on a click and on a right-click, and said the editor "should not be affected at
all by the terminal". That this was the cause of those reports is my reading, not something
seen: none of it was looked at in a browser. The editor gets as much room under its last
line as the open panel covers, so a file's end can still be scrolled into view. That room
is not taken back while any of it is on screen (`covered()` in `terminal-panel/terminal.js`):
the user reported the page scrolling on a right-click again the same day, "not all the
time", and with the file's end scrolled up above the panel, the press that hid the panel
took the room away and the browser moved the file down by as much. That this is what the
user saw is again my reading: whether the terminal was open was not said. The rule was run
on made-up numbers; not in a browser.

**A terminal is never restarted by a rebuild.** It forks the shell as its own child, so a
restart kills what runs there, most likely the rebuild itself. NixOS: `restartIfChanged =
false`. home-manager: `X-SwitchMethod = keep-old`. nix-darwin has no such switch and reloads a
job whenever its definition changes, so the terminal's job contains no store path and no setting: it
waits for and runs `/run/current-system/sw/bin/eznix-terminal-start` (a script in `systemPackages`
that holds the port, key file, folder and shell), so a changed setting is a changed script and not a
changed job, and nix-darwin does not manage the job at all: `postActivation` copies its plist into
`~/Library/LaunchAgents` and loads it only when it is not loaded (`terminalPlist`), the macOS
counterpart of `restartIfChanged = false`, so not even a nix-darwin update that renders plists
differently reloads it; a changed file counts from its next load (since 2026-10-17; the settings were arguments in the job's text, and changing one reloaded it). Don't put anything that varies per build into
that job. The page instead offers a restart when the running terminal differs from the
current one. A terminal has one checksum (`STAMP`) over its program file and how it was
started (port/key file/dir/shell); `_terminal_for()` in the server computes the same thing
from the installed program and `[terminals.NAME]`, so those must be exactly the arguments
the module passes. The server compares the two (`_terminal_stale()`) and the ping carries
only the answer, `terminal_stale`; the page compares nothing. It was four values in the ping
and two ways of learning them until 2026-10; don't grow it back. The terminal's package has
no version in its name (`packages.nix`), or its store path, and with it the unit NixOS
watches, would change with every commit.

**macOS logs are in `~/Library/Logs`** (`eznix.log`, `eznix-terminal.log`), since 2026-10-17; they were
in `/tmp`, readable by every account. Changing the terminal's job for that made nix-darwin reload it on
the first rebuild, which killed the eznix shell the user ran the rebuild in and left the switch half done
(the terminal agent unloaded, old plists on disk). Run again from Terminal.app it went through ("that
works"). The job is now outside nix-darwin's hands (see "A terminal is never restarted by a rebuild"). The first
rebuild that moved it there had to be run from Terminal.app, since nix-darwin removed the old job and
that killed the eznix shell it ran in (the user always rebuilds in eznix's terminal).

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

**The icon is drawn by the server** (`_favicon_svg()`, `/favicon.svg?theme=NAME`): the logo
in a theme's `--logo-1` and `--logo-2` with nothing behind it,
read out of the theme's stylesheet with every `var()` followed, since an image has no
stylesheet. Those two colours are what the user settled on (2026-10-11) after trying a
section's name and the header's fill on the editor's page: every other arm all but vanished.
It then sat on a rounded square of `--bg2` (the header's fill) for some hours, until the user
asked for the installed app's icon to have no background of its own. On a Mac that came out
on a white plate in the dock, so the manifest names two icons: the bare logo (`"purpose":
"any"`), which the user wants on Linux, and a filled one (`"maskable"`, `?filled=1`,
`_LOGO_FILLED`) meant for the Mac. That a Mac's browser takes the maskable one and Linux's
the other is how Chromium is documented to choose, not something seen yet. It was nixpkgs' snowflake, copied in at build
time, so a checkout had none. The page asks for the theme chosen in that browser
(`_loadIcon()`); the manifest, which a browser fetches with nothing the page knows, names the
configured one, in the icon's address with a checksum of the picture, so that another theme
or another colour is another manifest. The logo's
geometry is therefore in two places, there and in `terminal-panel/terminal.js`. Seen by the
user on 2026-10-11, on a Mac with the app installed in Brave (Chromium 154): after the update
the browser replaced the installed app's icon without a reinstall, visible once the app was
closed and opened again ("it worked if i closed the program"). That was with the second
version of the icon, which has a width and a height; with the first, which had only a
viewBox, nothing had happened, though whether the size was why is not known.

**eznix in the application menu comes from the configuration** (`programs.eznix`, in
`options.nix`: `programOptions`, `appEntries`; NixOS and home-manager, not macOS). Since
2026-10-15 an entry opens its address in the default browser (`xdg-open`), a plain tab,
and `browser` and `windowClass` are removed options (`mkRemovedOptionModule`). The user
chose that after seeing the app-mode window under Plasma with Plasma's title bar and frame,
which the page cannot colour: the browser draws its own only with its setting "Use system
title bar and borders" off, which is in the browser's profile and cannot be passed on the
command line. A profile of eznix's own with that setting written in was offered and not
wanted, and so was the browser policy below again. Checked: the two entries' text evaluated
on a NixOS system, and the removed option's message; then the user, on Linux the same day,
"yes that works" (with which entries, `enable` or `apps`, was not said). Every entry is
named for its address, "eznix (https://router.lan:9090)" (`labelOf`), the user's choice the
same day over the address as the entry's description; it was named for the machine ("eznix
(HOST)", or the name in `apps`). Evaluated, not seen in a menu. What follows is the
app-mode entry as it was from 2026-10-13 to then:
a desktop entry that opens a Chromium-family browser in app mode (`--app=URL`) at the
address worked out from `services.eznix` (http or https, `localhost` or the machine's name,
the port), with the logo as a file made at build time by `eznix --icon THEME`
(`_icon_file_svg()`: no stylesheet, no `<use>`, an automatic theme as its light one). The
user asked for it after two tries at keeping a browser-installed app working across an
HTTPS switch were both reverted that day (see "HTTPS" under Nix): that app belongs to its
address, this one is told the address at every rebuild. It is separate from
`services.eznix.enable`, so a desktop can have the entry for another machine's editor
(`url`). The icon on the window and in the task bar depends on the entry carrying the name
the browser gives the window, taken to be `PREFIX-HOST__-Default` (`brave` for Brave,
`chrome` otherwise); that is from memory of how Chromium names such windows, not seen, and
`windowClass` overrides it. `apps` (name -> address) adds an entry for each other machine's
editor, "eznix (NAME)", the user's naming (`machines` was mine); evaluated, not seen.
`browser` is a package, Chromium unless set, started from its
own path: for the first hour it was a command looked up on the PATH, and the user's first
try, with only `enable` set, did not find chromium. ezconf's entry (`programs.ezconf`) is not the model: the user
said its icons were wrong. Checked: `eznix --icon` gives valid SVG; the option evaluated on
a copy of the installer's template (the address, the entry's name, the desktop file's text,
the system's derivation). Built, installed and opened by the user the same day, on NixOS
with Plasma: "the app works and has the right icon!"; with which browser was not said, so
the window's name is confirmed for one of the two prefixes only. Switching HTTPS off and
rebuilding was tried with it too ("yes that works"): the entry opens the new address. The
window that was open through the switch goes on showing the terminal reconnecting until it
is closed and opened again, which the user found possibly acceptable ("it might be ok").
In that window the browser's download bubble comes up off the window's left edge, only its
right corner showing (the user's photo, 2026-10-13, NixOS with Plasma, after an export); in
an ordinary window of the same browser it is where it belongs. The file arrives either
way. My reading, not checked: the bubble hangs off the toolbar's download button and an
app-mode window has no toolbar. An app installed from the browser has the browser's own
bar and shows it properly (the user, in Brave), and the README says so. Having the entry
open such an app was built that evening and taken out again the same hour (commits
`7123382` and `90ddda6`, `programs.eznix.install` and `desktopIcon`, NixOS only), at the
user's word: "this seems to complicated just for the download dialog to be visible". Do
not build it again unasked. What it took, and what was found on the user's VM (NixOS,
Plasma, looked at over SSH): a browser policy (`WebAppInstallForceList`) does make the
browser install the app by itself at its next start, with eznix's own name; written
through `programs.chromium.extraOpts` it goes to Chromium, Chrome and Brave alike, so each
installed a copy; the browser lists the app on its apps page, and writes a shortcut of its
own into the home folder that starts the browser by its bare name, which is not on the
PATH when the browser is only in the store, so the menu showed nothing, and that shortcut
has the file name an entry of ours for the app would have, so it stands in front of it.
The identifier Chromium gives the app can be worked out from its address (two rounds of
SHA-256, sixteen bytes, in the letters a to p) and came out right for eznix.
Talked through afterwards and not built, the user choosing to "keep it like it is for
now": the page writing an export itself through the browser's Save dialog, so that no
download note comes up at all; a window program of eznix's own on a web view; and the
browser's own setting "Show downloads when they're done", which nobody tried.

**The installed app's window bar has the header's colour** (`_loadWindowColour()`, the
`theme-color` tag in both pages, `theme_color` and `background_color` in the manifest). With
nothing said a browser chooses, and Brave took the profile's colour, which the user asked to
be rid of (2026-10-11). The page reads the colour off what it has drawn at its top, so it
follows the theme chosen in that browser, a user's own included; the manifest has the
configured theme's, for before the page is in. The tag is never empty: the page comes with
the configured theme's colour in it, and its first script puts in what this browser had
last time (`eznix-window-colour`). It was empty until the page was whole, and the user
saw the bar fall back to Brave's own colour after some of the reloads that follow an
update, until the app was restarted (2026-10-12); whether filling it early cures that has
not been seen. Seen by the user that day in the app installed
in Brave on a Mac ("it works!"); not said: whether it took a restart of the app, and how it
looks with an automatic theme.

**Sessions**: a random token per login in the `eznix_session` cookie, stored hashed in
`<state>/sessions.json`, so a restart of the server logs nobody out. How long a login lasts
is the server's doing, set under `[session]` (`session.*` in the modules); the cookie only
carries the token and gets the same lifetime. `days` unset, the default: it ends when the
page has not been heard from for 15 minutes (`SESSION_IDLE`; an open page pings), and a day
after the login at the latest. Set, it lasts that many days with no idle limit, 400 at most
because browsers cap cookies there; `renew` counts them from the last page load, which the
user wanted as a separate, explicit choice. Until 2026-10-11 the settings were
`session.cookies.*` and the default left it to the cookie, which had no lifetime so that the
browser would drop it on quitting, while the token had 400 days. The user's browser restored
the cookie with its tabs and never asked again ("if i quit the browser i dont have to login
again"), and found a cookie setting that decided nothing confusing. Renamed without keeping
the old names, on the user's word that nobody uses them yet. The two limits are constants,
not settings. It used to be fixed at 400 days and always renewed.

**`debug`** (off by default; `services.eznix.debug`, `debug` in `eznix.toml`, `--debug`) is
one switch for whatever is only worth knowing while something is being looked into, which is
how the user wanted it (2026-10-11): `_debug(line)` in the server writes to its log,
`api.debug()` is the same for a plugin, and `eznix.debug(...)` in the page writes to the
browser's console. Add a call wherever one helps. Never a secret in such a line (passwords,
session tokens, terminal keys, a file's content): the user's condition. Without it the log
has no line per request, only starts, logins and errors. The terminal program has no part in
it: any change to that file makes every installed terminal offer a restart.

**Requests must come from the page** (`_valid_origin()`): every POST but the login itself and the
`/terminal` handshake are refused when the `Origin` header names another address than the `Host` the
request was sent to, port included. The cookie's `SameSite=Strict` does not cover this, since
a page on another port of the same host counts as the same site. `hosts` is deliberately not
used for it, except for an entry that is a whole origin (`"https://name"`, for a proxy that
changes `Host`): the modules put the certificate's names in `hosts`, so matching host names
would let any port of the protected host through. `"*"` in `hosts` opens the host-name
check only, not this one (since 2026-10-18; it skipped both, so on the installer a page on
another port could save and open the terminal); `origin_check()` in `test_server.py`.

**A host name eznix was not told of gets nothing** (`_wrong_host()`, first in `do_GET`,
`do_POST` and `do_HEAD`), since 2026-10-19: a 403 that says which name to add to
`certNames`, for every request, the login page and the login included. Against DNS
rebinding: a site whose name is made to point at this machine is, to the browser, this
server's own origin, so the Origin check above passes and only the name tells it apart.
Before, only the POSTs after the login asked, and such a page could log in and open the
terminal (its handshake is a GET); with curl against the test server under `Host:
evil.example` the login gave a cookie and the terminal answered 101. It needed a password,
except on the installer, which had `hosts = [ "*" ]` with its public one (`nixos`/`eznix`)
and passwordless sudo; the installer dropped `"*"` the same day, an address being let
through anyway and the machine's name being listed by the module. Found in a review the
user asked for; in `test_server.py`. Not tried in a browser or on the installer.
The terminal program compares its key in constant time everywhere, as of the same day. `/logout` is a GET and is not
checked: a page on another port of the host could log the user out, which also ends their
shell (`terminal_end_on_logout`). Any other GET that changes something would need the check.

**Where eznix is reached is dnsmasq's and Samba's model**: `interfaces`, a list of network
interfaces, and optionally `listenAddresses` (`listen_addresses`), a list of addresses that
narrows it. One listening
socket per interface (and address), tied to its interface (`_bind_to_interface()`:
`SO_BINDTODEVICE` on Linux, `IP_BOUND_IF` on macOS), so eznix itself takes nothing that
arrives through another, whatever a firewall says: the user wanted that as a setting of
eznix and not a firewall rule beside it, which on a router with its own rules is all that
can be relied on. Through an interface it is every address that has, so DHCP needs
nothing. `lo`, the machine itself, is an interface like any other and the default, `[ "lo"
]`; an empty list is every interface (an installer cannot know their names). One that is
not there is left out with a line in the log, as long as another is. On NixOS
`openFirewall` opens the port on the listed interfaces only.
How it came to this, all on 2026-10-12, with nothing kept for compatibility at the user's
word ("nobody is using this yet"): it was `listen`, one address, and `interface`, one name
that shut the machine itself out. The user changed the address in the editor, rebuilt, and
had no page left to change it back in. A `localhost` switch with a fallback was my first
answer; the user called it hacky and had it removed ("i need it to be secure"), proposed
the list with `lo` in it, asked what nginx does (addresses only, the interface left to the
firewall: what ezconf did, and the weak spot on a router), and chose the model that names
interfaces once told that dnsmasq and Samba are it.
On 2026-10-13, on NixOS: `openFirewall` is refused unless it is told where, by `interfaces`
written (naming something other than `lo`, or `[ ]` for every one) or by `listenAddresses`
(then one rule for every interface, eznix answering on those addresses alone). It used to
open nothing, silently, with the defaults. The user's reason: whoever opens a port should
have to understand what the settings do. `"all"` as a name in the list for every interface
was built the same day and dropped again, since a word among interface names looked strange
to the user; `[ ]` stays. Evaluated on a copy of the installer's template for eight
combinations, with the ports each one opens; nothing was rebuilt with it.
Later that day the user, about to set `listenAddresses` alone, asked whether that would
work. It would not have: the address was tied to `lo`, the default, so nothing arrived from
the network and `localhost` was gone as well. Now `interfaces` not set is `[ ]` when there
are addresses (the option's default in `options.nix`, and the same in `eznix.py` for a
configuration without the key), and an `interfaces` that is written is used as written;
`localhost` is then not answered unless `127.0.0.1` is listed, which the user found right
("they probably dont want it"). Adding the two lists up, as dnsmasq does, and addresses
per interface were both talked through and not built. Checked: the module's default for
each combination, and on a Mac that an address with `lo` named still answers there; an
address alone could not be reached from the shell it was tried in, where a plain Python
server on that address could not either, so it has not been seen answering. On
2026-10-15 the user, on a Linux VM, set an address alone with `openFirewall` and reached
eznix from outside ("seems to work"); without `openFirewall` it was not reached, as it
should be. Whether `localhost` then stayed unanswered was not said.
It is IPv4 only: the sockets are `AF_INET`, and an IPv6 address in `listenAddresses` is
left out as one that cannot be listened on.
Tried on a Mac: the default, `lo` with a real interface, a real one alone, the empty list,
a missing interface beside `lo` and alone, and with addresses; the NixOS module evaluated
for the same. On Linux by the user's word the same day, on two NixOS machines rebuilt to it: the
router, with `interfaces = [ "lan" ]` and opened as `ezbox.lan` (a name eznix added by
itself), and a desktop on the default `[ "lo" ]` ("both machines seems to work"). Two
interfaces at once, where two sockets share a port by being tied to different interfaces,
by the user's word on 2026-10-15 ("seem to work"; which two was not said). A missing
interface alone, the same day: the rebuild went through and the service did not start, as
meant (the build cannot know which interfaces the machine will have). Beside `lo`, also
that day: it started on `lo` alone ("works"), with HTTPS on, as it should be: the build
takes any name other than `lo` for a way in from outside.

**Reached from elsewhere, what eznix cannot know goes in `certNames`, by hand.** What it
can know it takes by itself since 2026-10-12: the machine's host name (`hostNames` from the
NixOS and nix-darwin modules: the name, with its domain, and as `NAME.local`; home-manager
has none to give) and the addresses in `listenAddresses`. eznix
doesn't know what will be typed in the browser, so the certificate names only localhost and
any other name is refused until it is listed (only saves were, until 2026-10-19). A plain address is not
(`_valid_host()`, since 2026-10-12): the check is there against a foreign name pointed at
this machine, and an address is no name. Before, an address had to be listed too and the
rebuild stopped on an empty `certNames`; the user, with a VM on DHCP and `interface`
alone, had saves refused from another computer, added a name they did not open it by, and
said of listing the address "i could as well put listen = dhcp". The refusal now says in
the page which name to add. Looking the machine's addresses up
(an ioctl per request, and again for the certificate at start) was built and taken out
again on 2026-10-09: the user found it hacky and prefers a certificate that is plainly wrong
until `certNames` is set, with the options' descriptions saying so. Those descriptions are
what the editor shows as a setting's help, so they are the documentation that matters here.

**Login**: system passwords are built in (`users`; PAM in-process, or `auth_helper`). Any other
way is a plugin calling `api.login(check, user)`; the shipped `password` plugin is the one
configured password. System login is on when `users` is set or no plugin brought a login, and
eznix refuses to start if nobody could log in.

**The login page** (`webroot/login.html`, filled in by `_read_login_page()`) is the logo over
a centred "eznix (hostname)", two fields that say what they are for when empty, and the
button, as the user shaped it on 2026-10-11. The fields are the one place not in the theme's
font: Chromium shows a saved login, while it is only offered, in its own `sans-serif` at
13.33px and nothing overrides that, so the fields have that font to begin with (the comment
there has what was tried). No name is filled in or offered by eznix, whoever
could log in ("the user must know its username"): it came filled in for a single user, and
had an arrow listing them for several, until that day. Choosing a saved login puts the cursor on Sign
in; Tab is the browser's own. Seen by the user in Brave, Chrome and
Firefox that day ("looks good in firefox and chrome").

**eznix installs nothing in the folder it edits.** `json2nix.nix` used to be copied there as
`default.nix` (`imports = [ ./eznix ]`); the user chose the function instead
(`lib.jsonDir DIR`, or `{ dir, exclude }`), so the folder can be one with a `default.nix` and
other JSON of its own, the flake's root included. `exclude` exists twice and the two must
agree: the function's argument keeps a path out of the build, the editor's setting
(`_excluded()`) keeps it from being a tab. Its entries are read like the lines of a
`.gitignore` since 2026-10-12, at the user's wish (plain paths from the top before): a name
at any depth, `/name` anchored, `* ? [a-z] **`, `!entry`, last match decides. Each side
turns an entry into a regular expression by the same steps (`_exclude_rule()` in
`eznix.py`, `nix/exclude.nix`), and `test/exclude.json` is one table of cases both are run
against (`test_server.py`, `checks.exclude`): add a case there when touching either. The system
plugin's own `exclude` (what an export leaves out of the whole flake) is read the same way,
through `api.ignore()`, and is the one setting for it, `[".*"]` by default; it was a switch
`dotfiles` and a list of exact file names, which the user had made one ("it should be one
option and default to excluding dot files"). An import still skips every dot path in a
zip, whatever the setting. What
changed for an old list: an entry without a slash now matches at any depth, not only at the
top. A module can't pass its option to the function
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
harmless with the official installer. All three build on the stable release, `26.05` at
the time (nixpkgs and, where there is one, the branch of nix-darwin or home-manager that goes
with it), with the rolling ones named in a comment for whoever wants them, and so does
eznix's own `flake.nix`: the user's choice on 2026-10-12, after a test install showed the
Quick Start taking a fresh 26.05 machine to 26.11 ("go against stable", "people who are more
advanced" can change it). The number is in each `templates/*/flake.nix`, in `flake.nix` (its
own nixpkgs, and the first-switch commands in the templates' `welcomeText`, which named the
rolling nix-darwin and home-manager until 2026-10-13) and
in the README's first-switch commands for the Mac and other Linux, and has to be raised by
hand when a release comes out, in May and November. There is no `flake.lock` in the
repository, also by the user's choice ("i dont want to update the lock-file manually"), so
`nix flake init -t` prints a harmless "not writing modified lock file", and running or
building straight from GitHub needs `--no-write-lock-file`, without which Nix stops with
"cannot write modified lock file" (the user's catch, 2026-10-13; the README's "Try it" had
the bare command until then, as had the installer's Quick Start). The one thing to fill in is
`YOUR-USER-NAME`; an assertion in `options.nix` catches it left in. They name
`github:kalken/eznix`, so they are only as new as what is pushed; to try one against the
checkout, `--override-input eznix path:.`.

**A system import takes only a zip of a system** (`prepare()` in the system plugin): one
with `flake.nix` at its top, as an export and a backup have. Any other is refused before the
snapshot and before anything is touched, saying where its `flake.nix` is if it has one deeper
down. Before 2026-10-13 any zip was taken, and since the tree is made to match the zip, one
that was not a system removed every file of the flake that it did not hold (the backup
taken first was the only way back). The user asked for the check. In `test_server.py`.

**A system import leaves the machine's own hardware file alone** (`keep` in the system
plugin, `prepare(zf, keeping=True)`): what the setting names, `hardware-configuration.nix`
unless set, is neither replaced by the zip's nor removed for not being in it; a machine
without one takes the zip's. The user's wish on 2026-10-13, about to import a template made
on a VM onto another box; generating a new one was the first idea and is not something an
unprivileged eznix can do. A restore keeps nothing back. In `test_server.py`. An import
through the page was tried by the user the same day: export, one Markdown file removed,
the export imported again, which brought the file back, with the backup taken first the
smaller for it ("it seems to work"); on which system was not said.

**Systems can be imported from places named in the configuration** (`sources` in the
system plugin, 2026-10-19, the user's idea: "import systems from an url, listing a
folder/zip hierarchy"): a zip, whose every folder with a `flake.nix` is a system (a GitHub
archive as it is, its one folder around everything left out of the names), or a JSON index
of zips, folders and other indexes. The server downloads (https only, or a path on the
machine; kept in `system-sources/` for ten minutes, and used when the place cannot be
reached), lists them as a tree for the System menu, and imports one folder of a zip by
making it a zip of its own and handing that to `prepare()` and `apply()`, so it is an
import like any other. The page names a system by location and folder, and only a location
a listing of the setting reached is taken (`reached`): nothing typed in the page is ever
fetched. In `test_server.py` (`system_sources()`, local files only); downloading and the
menu in the page were not tried.

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

**The suggestions are parsed by their form, never by an option's name.** The user's rule,
set on 2026-10-10 after two fixes that had each been shaped by the one option being looked at
(networking.hosts): as general as possible, because most options are never looked at by
anyone. In `index.html`: a part of a path in angle brackets is a placeholder whatever it says
(`_isWildcard()`; nixpkgs has `<name>` but also `<path>`, `<config-name>`, and others); a
quoted part is one part (`_pathParts()`); a type is a set if it says "attribute set", under
any wrapping (`_setEntryType()`), and what is inside a set has the type the set says it holds
(`_typeAt()`), so a new entry can be added to any of them. One thing can't be read off: whether
a dot typed after a set belongs to the entry's name. It is taken as part of the name only
where the entry is certainly a plain value (`_isPlainType()`, a list of what is known), since
types are free text and a wrong yes would glue a section and its key together; everywhere else
a dotted name needs its quotes, as in Nix. `checkOptionParsing()`, from the browser's console,
runs every option of the loaded suggestions through all of it and lists what fails: none of
27,654 on NixOS and of 1,257 on nix-darwin when it was written. Run it after touching any of
this, on both kinds of data.

**Nothing touches disk until Save**, including deletes, renames and moves (`pendingFsOps`,
replayed in order). Undo is one global stack of full-state snapshots and survives a reload.

**Going back past a Save** (`_rebaseHistoryOnDisk()`, run after every Save): each other point
in the undo stack is told what is on disk now, its `fileSaved`, `folderExists` and
`pendingFsOps` worked out again against it. Before, a point kept what was true when it was
taken, and going back past a saved delete brought the tab back with Save grey. Undo never
changes the disk: the earlier state comes back as unsaved changes. No folder delete is ever
queued by it (a folder can hold files eznix shows no tab for); one made since stays as an
empty tab. The case it was made for the user tried in the page on 2026-10-11 ("remove file,
save, undo save works"); renames and folders only as a function on made-up cases.

**The page starts with one request for all the files** (`/api/v1/files?content=1`, compressed)
and asks for the suggestions at the same time (`_fetchAutocompleteData()`,
`loadSiblingFiles()`). It was a request per file and then the suggestions, each a
connection of its own.

**Connections are kept open and used again** (`StaticHandler`: `protocol_version`, `timeout`,
`end_headers()`), since 2026-10-11; before that every request was its own connection and,
over HTTPS, its own handshake. One place decides: a connection stays open after an answer to
a GET or HEAD that went well and has a `Content-Length` (or no body); it closes after a POST,
an error or refusal, and any answer whose end is the close. A POST always closes because one
refused early leaves its body unread, where the next request would be read out of it. What a
handler keeps about a request is reset for the next (`handle_one_request()`); the terminal's
socket takes the idle timeout off itself (`_proxy_terminal()`). Tested in headless Chrome,
with and without HTTPS: a page load is 17 to 23 requests over 8 or 9 connections, saving
works, and a terminal left silent for 75 seconds stays connected. Why it was done: on a
rebuild of the user's router the browser held its requests back for most of a minute, with
eznix up and idle by its own log; the cause was not found and it did not happen on one
machine, so whether this cures it is not known.

**The page, its stylesheets and its scripts are kept by the browser and checked on every
load** (`_unchanged()`, `_send_validator()`): `private, no-cache` with an ETag that is a
checksum of the file, so the answer is a 304 while the file is the same one and the file
itself the moment it is another. Never the address-with-a-checksum way of caching: the user
wanted to be sure that whatever an update changes arrives. API answers stay `no-store`.
Answers say HTTP/1.1 for this (`protocol_version`):
Chrome does not keep a *page* it was sent as HTTP/1.0, and fetched `/` in full on every
load while the files beside it came back 304 (found and checked in headless Chrome,
2026-10-11; the server's log shows the 304 for `/` now, DevTools reports it as 200).

**Nothing is shown until the page is whole** (`booting` on `<html>`, taken off at the end of
`_init()`, or after three seconds whatever happens): a browser keeps the old page on screen
meanwhile, so a reload has no header filling in and no "Loading…".

**The editor's layout is boxes and rows, with the numbers in the themes.** Settled over a
long afternoon (2026-10-11) of the user pointing at one gap after another; read the comments
in `style.css` before changing any of it, since most of what looks adjustable there was
tried and taken back. As it stands:

- A top-level section is a card. What is in it is a stack of boxes, each with a line along
  its top and the same padding above and below (`--card-gap`): a sub-section is one, and so
  is a run of plain options. A run of options is an element, `.field-group`, made by
  `renderObj()` (not at the root of a file); nothing that moves or finds rows goes by their
  place among siblings, so the wrapper is invisible to drags (the user tried: "drag drop
  works"). No rule looks at what is next to what.
- Inside a box everything is a row of `--row-height` (24px) with its text 4px from the top:
  a heading, an option's name, the text of a value. Rows follow each other with nothing
  between, so lines of text are evenly far apart. A strip of values has 4px below it
  (`.field-group`'s padding), since it is filled to the bottom of its last row.
- The indent is `--indent-step` (2ch; 1ch was tried on 2026-10-15) per level and nothing
  else, and a setting since that day (`indent`, in characters, 2 unless set, `services.eznix.indent`;
  the server puts it in the page as `html:root`, which outweighs every theme's `:root`): a section's options start one step in from its name, and no arrow takes room in
  the text. Until 2026-10-15 the arrow of level 3 and down was part of the heading's text,
  two characters wide, and the user found the names too busy with everything unfolded; it
  was taken away altogether for a while that day (a click on the name folds). Arrows and a line down the section shown only under the pointer were
  tried the same day and turned down: the user does not want the page to change when the
  mouse only moves. A folded section has an arrow (▸) at every level, an open one (▾)
  from `arrowLevel` down (`arrow_level`, 3 unless set, 0 for none; a setting since the same
  day, at the user's wish); each hangs to the left of the name, outside the
  text, so that it moves nothing (the user: "the arrow should never affect the text
  placement"). Both settings at 1 were seen by the user in the test server that day
  ("that works").
- Below level 2 a section has no line, box or shade of its own, only its indent. Turned
  down by the user on 2026-10-15, each tried in the test server: a shade per level, boxes
  and lines along the top taking turns as levels 1 and 2 do, the box as a line down its
  left only, those lines fainter, soft shadows in their place, and box / top line / left
  line in turn. The comment in `style.css` has the list.
- A value is 8px from its strip's left and right edge and 4px from the top of its row.
  Giving the strip room of its own above its first value was tried and made the rows
  uneven; the user chose even rows.
- An object in a list is a box of its own in the section's colour, its values 4px in from
  its top, bottom and right and its names one indent step in from its left.
- The same in every theme: all eight set the layout variables to the same values, and a
  theme could draw a line round a card or a value strip through `--card-border` and
  `--value-border`. No built-in theme does: `breeze-*` did for an afternoon, to copy Plasma's
  settings surface by surface, until the user found the result horrible and had both rebuilt
  by the rules in `THEMES.md` like the others, with Plasma's colours.

**A theme that copies a desktop is made from a screenshot of its file manager** (THEMES.md,
"A theme from a screenshot"), the user's idea on 2026-10-13: the window's own surface is the
bars and the sections, a panel of another shade the editor's page, a sidebar entry a tab
(`--tab-bg`, `--tab-border`, new that day so a tab can be a bare name) and the selected one
the open tab (until 2026-10-14, when the user had the open tab look like a selected button,
`.btn.active`, in every theme, and `--tab-active-*` went); popups have the bars' colour. Measured in the picture's pixels, converted to
sRGB (a Mac's screenshot is in the display's profile; `sips -s format bmp` converts). Done
for `osx-*` from Finder, `breeze-*` from Dolphin and `gnome-*` from Files (run under
Plasma with `nix run 'nixpkgs#nautilus'`); the first two pairs were seen by the user in the
test server, but for `breeze-light`. Sections and bars are one colour in every theme, also the user's rule that day.

**The theme a browser starts with follows the system eznix runs on, in the modules**
(`defaults.theme`): `osx` on macOS as before, and since 2026-10-13 on NixOS `breeze` with
Plasma or `gnome` with GNOME when that is the only desktop enabled, `nixos` otherwise (both,
or neither: the user's "go back to blue if nothing fits"); home-manager cannot know and has
`nixos`. Not in the page: a browser can tell a Mac from Linux but not one desktop from
another. It is the machine's desktop, not the browser's. Evaluated for none, each, both and
a theme set by hand. On 2026-10-15 the user reported `breeze` chosen by itself on NixOS
with Plasma; GNOME's and the fallback to `nixos` not seen.

One mistake worth knowing about: a block of these rules (the name column's width, the indent,
the heading's padding) was deleted by an edit that replaced "everything between two comments"
in `style.css`, was pushed, and was then papered over with workarounds for an hour before the
cause was found. Edit that file by exact strings.

**Adding**: a list ends with a "+" that adds an item (`addItem()` in `renderArrayField()`)
and an object in a list with a "+" that opens the add field for it (`renderObj()` with
`addLine`), both in the page (`_addButton()`; they were the words "Add item…" and "Add
option…" across the line for some hours, until the user asked for a button); a section has
the entry on its right-click menu (`_addMenuItems()`), and the editor's blank space has "Add
option…" for the file. One rule says whether it is there (`_addLineFor()`): always, except where
every option the suggestions list is already set *and* the object certainly takes no others
(`_takesOnlyDeclared()`: a group of options with no type of its own, or a plain
"submodule"; anything unreadable counts as free-form, after the entry went missing on
`services.samba.settings.global`). It reads "Add
option…" everywhere; a set said "Add entry…" until the user chose one wording that day. Settled on 2026-10-12: only an empty list had a line
before, and the menus had an entry per kind of thing pointed at ("Add sub option…", "Add
field", "Add entry…" on an entry, "Add item"). For an hour every object had the line, the
file and each section too; the user looked and kept it for lists ("its better to have it as
rightklick, but for lists its great"). A click on a whole option in the add field's list
adds it at once. A path the suggestions do not know is never refused: Enter on it brings up the
bar that asks what kind of value it is (`doAdd()`, `doForceAddWithType()`), where it used
to say "Unknown option path" as long as anything was still suggested for what was typed.
The same bar comes for a new entry of a set that leaves open what it holds (`_saysNoKind()`:
a bare "attribute set", or one of anything, of a JSON value and the like), since 2026-10-13:
it was added as a text without a word, which the user met on a list under
`programs.chromium.extraOpts`. Checked by running the rule on type texts; not in a browser.
The bar's buttons and Add keep the cursor in the field, since the field's blur hides the bar.
Tried by the user in the test server that day, on `services.samba.settings.global` ("that
works!"): the type chosen from the bar, and Add pressed with no type chosen.

**Sections start out folded from a level**, `collapseLevel` (`collapse_level`): a number, a
top-level section being 1; not set (null), the default, nothing is folded
(`SECTIONS_LEVEL`, `_sectionStartsOpen()`). Until 2026-10-12 the setting was `sections`,
collapsed or expanded, collapsed by default, with the level fixed at 3, the first level
that could be folded then: levels 1 and 2, the cards and the boxes in them, had no arrow
until the user asked for those to fold too the same day, by a click on the name and
without an arrowhead (`.foldable` on every section; level 3 and below kept theirs until
2026-10-15, see the layout above, and are marked `.nest-deep`).
The user wanted the level settable. It went through 4 as the default ("collapse after level
3"), one setting taking either word or a number (unclear, the user found), and one number
with 0 for never (my suggestion), until, having seen everything open in the test server,
the user made that the default and null its value ("maybe unset collapse level should be
null actually"). The old setting still works, read as 3 or as not set
(`mkChangedOptionModule` in the modules, and in `eznix.py`).

**A right-click brings up the menu of what is under the pointer** (`_onRowItself()`): an
option's for the text of its name or its value, and for the empty part of its row the menu
of what the option lies in, the section, the object in a list or the file. The user's rule,
2026-10-12; the whole row was the option's before. The name is its text (`.tt-anchor`) since
2026-10-13: the test went by `.key-label`, which is as wide as the name's column, so the
room beside a short name still brought up the option's menu. Tried by the user in the test
server that day ("i think this works for everything. hard to test everything though"); not
in a browser by me.

**Copy and Cut also put the thing on the computer's clipboard** (`copyPath()`,
`_asImportText()`, `_toSystemClipboard()`): as JSON, wrapped in the sections it lies in, which
is what Import takes, so a section goes to another computer by Copy there and paste into
Import here. The user asked how to do that on 2026-10-13; before, Copy only filled the
page's own clipboard, which reaches the files of that page. Something inside a list is put
there bare. Over plain http `navigator.clipboard` is not there and the text is copied out
of a hidden field instead. The text was checked by running the function, lifted out of the
page; that it arrives on a clipboard was not, in either way, by anyone.

**A suggestions file that is not there is answered with 204, and one outside their folder
not at all** (`_serve_autocomplete()`, the `/autocomplete/` branch of `do_GET()`). Nothing is
generated until somebody runs the generator, so a missing file is an ordinary state: it was
a 404, which a browser writes in its console at every load, where the user found one for
`choices.json` (2026-10-13). While changing that I tried an address with `..` in it and got
`/etc/hosts` back: the path was only tidied with `normpath`, which leaves leading `..` in,
so anyone logged in could read whatever the eznix process can, its state folder included.
It is now resolved (`realpath`) and has to lie inside the folder. In `test_server.py`, both.
The user then asked whether that was all of the kind, and every place a request's value
becomes a path was read and tried with hand-written addresses on the test server (a Mac):
the page's files, `/terminal-panel/`, `/theme-*.css`, `/plugins/`, the file, folder and
backup calls, the documents, files and system plugins, the icon's `theme`, and what answers
without a login. One more turned up: a plugin's server file, `plugin.json` and `README.md`
were served when asked for in other letters (`system.PY`), on a disk that does not tell
them apart; the test of the name is now made in lower case. A system import was already
closed (`prepare()` in the system plugin skips an entry with `..`, an empty or a dot part,
and refuses the whole zip when a path resolves outside the flake, as through a link in it);
`test_server.py` now imports zips made to get out, both ways. Not looked at in that pass:
what a zip can do other than by its paths (its size, say).

**Nothing from a file or a module goes into the page as markup** (2026-10-16, the user asked
how safe the page was against bad input and then to make it secure). A script that runs in
the page can use the whole API and the terminal, which is a shell as the user, and the
page took markup from places a flake gets from others: a `.md` file (the Documents plugin
let raw HTML and `javascript:` links through, on the thought that the files are the flake's
own), a key in an imported JSON file (the "Add option" list), and a description, default,
example or type from a module taken from elsewhere (the lists and tooltips). Shown by running
the parser outside the browser on `<img src=x onerror=...>`. Now every such value goes
through `_escHtml()` before `innerHTML`, and `parseMarkdown()` escapes `<` outside code and
allows `http(s)`, `mailto` and scheme-less addresses in links and images (`safeUrl()`: control
characters dropped first, `&` and `"` escaped, so `jav&#x09;ascript:` and a tab inside the
scheme do not get through). A new `innerHTML` with a value in it needs `_escHtml()`; the
rest of them hold fixed text. Answers also carry `X-Frame-Options: DENY` and
`X-Content-Type-Options: nosniff` (`end_headers()`; the types are checked in
`test_server.py`), and the JSON put into the page escapes `</` everywhere, not only the
plugins'. Under the escaping there is a `Content-Security-Policy` on the page and on the login
page (`_csp_scripts()`, `_csp_header()`), as the second layer: scripts only by hash. The
server hashes every inline `<script>` of the page and every `onclick="..."`-style attribute
written in the page or in a script file that puts markup in it (the terminal's, a plugin's),
at the time it renders the page, so nothing is listed by hand and a handler is allowed by
being written there; `'unsafe-hashes'` is what lets a hash cover an attribute. A script a
file or a module writes into the page has no hash and does not run. Styles may be inline,
everything else is this server only, and the terminal's WebSocket is named by the `Host` the
page was reached by (`'self'` does not cover a WebSocket in every browser). **A new handler
built from a variable (`onclick="${x}"`) or by concatenation is not found by the scan and
is blocked**: write it as a plain string, or set `el.onclick = fn`. `test_server.py` reads the
page with `html.parser` and checks that everything inline is in the policy. Opened by the
user in the test server the same day: "it seems to be working" (what was used, and whether
the console was looked at, was not said). Not tried in a browser by me.
No `Referrer-Policy: no-referrer`, on purpose: with it a
browser leaves `Origin` off a same-origin POST, which `_valid_origin()` goes by.

**A POST has a size** (`_body_too_big()`, at the top of `do_POST`): the length has to be a
plain number (400), at most 16 KiB for the login, 64 MiB for the API and 512 MiB for a
plugin (413), checked before any handler reads. Nothing asked before 2026-10-16, and the
login, which anybody can reach, took what it was told (a negative length read until the
client hung up). A zip taken as a system has limits too (`prepare()` in the system plugin):
100,000 entries, 2 GiB unpacked, 1 GiB for one file, by the sizes the zip declares, which
bind what is written since reading stops at them. Both in `test_server.py`.

**Not limited, on purpose: tries at a system password.** A web login is limited per address
(`LOGIN_MAX_ATTEMPTS`). A lockout per user, or one in the setuid helper, would let anyone
who can reach the page lock the real user out, and those in the group `eznix` can already
write JSON that is built as root; PAM's own delay of a failed try (about two seconds) stays.
Talked through with the user as a gap and left; build it only if asked, knowing that. Checked by
running the parser on fifteen hostile and ordinary inputs and the page's scripts through a
syntax check. Then opened by the user in the test server: "it seems to be working from what
i can tell" (which of the lists, tooltips and documents were looked at was not said).

**A button can say what it does** (`description` on an entry of `services.eznix.buttons`,
`_buttonTip()` in `terminal-panel/terminal.js`): its tooltip then has that on a line above
the command, in the bar and in a menu alike, and above the "Saves your changes first" of a
`save_first` button. The user's wish, 2026-10-13. Checked by running the function and the
save mark's, lifted out of the page; not in a browser.

**A tab can be given a place** (`_tabOrders()`, `_tabSort()`, `services.eznix.paths.PATH = {
order }`, the option in `options.nix`): lowest first, a tab without a number counting as 0,
equals by name as before; a folder among the folders, a file among the files of its row.
PATH is the tab's path as the tabs show it, a folder's name or a file's path without
`.json` (`_folderLabel()`, `_filePathLabel()`). Made the way a menu's `order` is: read by the
page straight from every file, a later file's over an earlier one's, nothing switched off;
the bar is drawn again when the numbers change, also while one is typed. Not in
`eznix.toml`. It was `services.eznix.folders`, for folders only, for some hours on
2026-10-13 (commit `016e800`), asked for by the user as "order number on folders as we did
for buttons"; the user then wanted files too and one setting for both, and the first name
was dropped without being kept. A path that matches nothing is ignored without a word: the
user's first try had `user` for a folder `users` and seemed to do nothing. Folders were seen
working by the user that day on a real flake ("that works perfectly"). The version by path
was checked by running the functions, lifted out of the page, on made-up files; not in a
browser, and `options.nix` was only parsed.

**Every right-click menu is laid out by one rule** (`_menu()`, `_MENU_GROUPS` in
`index.html`): a menu says what it offers in named groups and the groups come out in one
order with a line between them: `add` (Add option…, New file), `item` (Rename, Disable or
Enable, Clear, Delete), `convert`, `clipboard`, `view` (Expand and Collapse all), `transfer`
(Import, Export, by themselves and in that order, the user's wish the same day), `disk`
(Backup, Reload), `restore`. The user's rule, 2026-10-13: entries that belong
together stand together, Add first, the thing's own entries next. Before, each menu was a
list written out where it was shown, and the same entry stood in different places. What it
moved: Delete from the end of an option's menu up beside Rename and Disable; on a file's
and a folder's menu Export from the top to below Disable and Delete, which undoes "Export,
Import and then the rest" as the user had set it for a file (that order still holds inside
the group; the system plugin's menu, which is not one of these, has Import before Export
since 2026-10-13 as well); a file's Clear and
Delete now say "file", since on the editor's blank space they stand near the top. A
disabled option has Copy and Cut like any other. The menus of buttons (the terminal's, the
plugins') do not go through it. Checked by running the builder and the functions that feed
it, lifted out of the page, and reading the order of each menu; not in a browser by me. Seen
by the user in the page that day ("rightclick menu order is good now, import and export are
its own with dividers"); which of the menus were opened was not said.

**A path goes on inside what is switched off** (`_enabledValue()`, `getAtPath()`,
`_holderOf()`, `traverseForSet()`): a disabled option or section is stored as `{_disabled,
_value}` in its place and drawn as its value, so every path of something shown in a disabled
section passes through a wrapper. What lies at the end of a path is still given as stored,
wrapper and all. Until 2026-10-13 no path went through one: the user saw "[object Object]"
in the dropdown of a disabled option, asked whether there were more of the kind, and inside
a disabled section there were: nothing was found by its path, Delete did nothing and
Disable wrote an entry into the wrapper. Whatever replaces a section's content (rename,
reorder) goes through `_contentAt()` and `_setContentAt()`, which keep the wrapper. Checked
by running those functions, lifted out of the page, on made-up data (reads, set, delete,
rename, reorder and add, in a disabled section, a list in one, and ordinary ones); not in a
browser. "Add option…" is on a disabled section's menu since then, like any other's
(`_addMenuItems()`); it was kept off while adding there wrote into the wrapper. Adding an
option to a disabled section was tried by the user in the page that day ("that works"). Merging follows the same
rule (`_mergeOrReplace()`, which `_nixDeepMerge()` comes back to at every depth): a paste, a
drag onto another file's tab or an import onto something switched off merges with what it
holds, and the result is switched off if either side was, so nothing that was off comes on
that way. That last part is my choice, not something the user said. Checked the same way.

**Lists**: Nothing
removes an item by itself: Backspace in an empty plain item, or in an empty text field of an
object with nothing in it, and Delete on the menu. On 2026-10-11 an item just added and left
untouched went again on a click elsewhere, and the only item of a list went the moment it
was emptied; the user had both taken out the next day ("dont remove fields that are empty
automatically"), once adding had its own lines in the page. The Backspace part was tested in
headless Chrome with real keys on 2026-10-11; the two lines to add with were not run in
a browser by anyone but the user, who has not said that they work.

**A name being renamed does not move** (`_startKeyRename()`, `.key-rename-input`): the name
stays in the page, unseen, and the field lies on top of it in the same font and colour, its
frame a shadow. The user's wish ("i dont want it to move at all"); the field used to take the
name's place, 22px tall in a 14px line. Measured in headless Chrome on 2026-10-11 for an
option, both kinds of heading and a top-level title, and seen by the user ("its perfect now").

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
"x.py"}`, all but the name optional. Found in `plugins/` (beside `webroot/`) and in `plugins_dir`
(`_load_plugins()`); `[plugin.NAME]` in the config holds its settings, `enabled = false`
leaves it out. Nobody outside eznix depends on the interface yet, and the README says it may
change, so it can be reshaped freely.

- **Page side**: its scripts are loaded after the page's own script and before `_init()` runs.
  They share the page's global scope, which is what let existing code move out unchanged; the
  page itself only ever reaches a plugin through `eznix.emit()` events (`init`, `ready`,
  `render`, `dirty`, `theme`, `ping`), and `eznix.addButton()`. All of
  it is documented at the top of the main script, under "Plugins". The page must never name a
  plugin's function directly, or it breaks when that plugin is left out.
- **A plugin looks like the page**: it uses the page's classes (`.btn`, `.modal`,
  `.modal-input`, `.modal-hint`, `.modal-error`, `.autocomplete-list`, ...) and the theme's
  variables, and its own stylesheet holds only what the page has no rule for (a size, a
  position). The user's wish, 2026-10-14, after the files plugin's dialog had a field, hint,
  error and a `primary` button of its own; the dialog rules were the Import dialog's
  (`.import-*`) and were given general names for it.
- **Server side**: `setup(api)` in the server file registers handlers under
  `/api/v1/plugin/NAME/` (`PluginApi`: `api.get/post`, `api.config`, `api.flake`,
  `api.state_dir`, `api.page`, `api.login`, `api.ignore`). A handler returns JSON-able data or an
  `api.Download`, and raises `api.Error(status, message)`. Core checks the login first. A
  plugin whose server file fails to load is left out whole.
- `.py` files, `plugin.json` and a plugin's `README.md` are not served to the browser.
- Each shipped plugin has a `README.md` in its folder, for users: what it does and a table
  of every setting, in the layout of the main one (the user's wish, 2026-10-12: "can you
  put an md file in the plugin"). The main README's Plugins section links to them and no
  longer describes them itself. Update the plugin's own page when a setting changes.

**The panels on the side are the page's** (`eznix.sidePanel()`): a plugin's panels are tabs
along the top of one window per `group` (the documents, the Nix files), and the windows
stand side by side over the right part of the editor, sharing its width evenly; the left
edge of the whole is the one to drag. The side is fixed in the window, from under the top
bars to the terminal's row of buttons, and does not follow the editor's height: the
terminal at the bottom comes up in front of it, so that an editor in a terminal there is
not resized each time ("it shouldnt affect the editor window, bottom terminal should just
show in front of it"). Settled in steps on 2026-10-12. The stack was the Documents
plugin's own, a window per open document; the Nix files then got a panel of their own that
lay over it and showed one file at a time, and the user missed having several things open
("the functionality to open many files at once ... is gone"); both became windows of one
stack in the page; and the user asked for tabs "in the editor window or document window"
instead of a window per file, and then for the two windows "side by side" and not one
behind the other. A plugin fills a panel's body and header and keeps its own
list of what is open.

**`files`** (2026-10-12, the user's idea) is menus of the flake's files by their kind: each
entry of `[plugin.files] menus` is a button with a `name`, the `extensions` it lists and the
`command` a file opens with, in a terminal of its own that is a tab on the side
(`openFlakeFile()`). With nothing set there is one, "Nix files" for `.nix` (the user went
from that to an empty default and back within the hour). The command is the menu's own, else the plugin's `editor`, else
`$EDITOR`, then nano; in Nix it can be a store path, which is how an editor set up in Nix is
used. A shell named after the file is started on `exec COMMAND 'path'`, so
leaving the program ends the shell and closes the tab. The tab's cross closes it too,
hanging up on the program with no question: an editor keeps what was unsaved in its own
recovery file (vim's swap file) and offers it at the next opening, which the user found
enough ("i think thats enough then"), after a time with no cross and one that asked first. The open files slide out of the way on a press outside the side, as the terminal panel
hides (`autoHide` in `eznix.sidePanel()`, `auto_hide` in the plugin, on by default, and the same for the documents; a
button brings them back), asked for by the user. That button is the terminal's own look
turned on its side, an arrowhead on a page button at the side's top left corner, and
hides by hand as well; away, the side has slid off only so far that this corner with the
button is still in the window, which the user saw and called perfect; before it there was a slim handle at the window's edge for showing
only, and for an hour a second one for hiding ("looks weird"). No buttons without
a terminal. Its server half lists files and deletes one:
each line of a menu ends in a cross, which removes the file at once after a question (and
closes its tab), and "New file…" is a dialog of the page's kind with the flake's folders
offered under its path field. It makes nothing: the program makes the file on its first
write, and a folder that is not there is made by `mkdir -p DIR && ` in front of the program,
for that open only, which the line under the field says as the path is typed ("Creates the
folder …"); the name has to end in one of the menu's endings. Until 2026-10-14 every open
ran the `mkdir`, and the first ending was put on a name without one. Having the plugin's
server make the file was built that day and dropped before it was finished: on NixOS it
would belong to `eznix`, fail where `flakeWritable = false` lets the user's editor write,
and stay behind empty if the editor was left without saving.
It went through several other shapes that day, which is why the terminal and the side
panels are what they are, and none of which should be rebuilt without the user asking:
- an editor of its own in the page (a text field with colouring drawn under it, suggestions
  from a scanner of Nix written for it, Save and Delete, backups, a parse check), taken
  out once a file could be opened in a terminal ("if we have vim we dont need any of that");
- as `nixfiles`, the same for `.nix` only with one `editor` setting, committed as `539cf28`;
- an editor shipped with the flake, `ezedit` (Neovim with nixd, a module, themes), built
  twice and thrown away twice the same day, never committed: first with completion from
  eznix's own data, then with only Neovim's standard parts. The user ended it with "lets
  skip this completely and do a simple solution" and asked for this plugin, general by a
  list. What they want from an editor they set up themselves, in Nix.
Seen by the user in the test server, with vim: as `nixfiles` ("wow that works perfect"),
and as this plugin the cross that deletes, with the tab closing ("thats good"). What else
of the menus and the dialog they tried was not said.

**The generator's plugins** (2026-10-17, the user's idea: "today we have home manager, brew
etc that are special"): what only some systems have is a plugin, not a branch of
`eznix-autocomplete.py`. `plugin.json` names a file as `"autocomplete"` with `generate(ctx)`,
`SYSTEMS` (the kinds of configuration it is for) and `OPTIONS` (it adds to `options.json`),
documented above `find_plugins()`. The kernels (NixOS), Homebrew's names (nix-darwin) and
home-manager's options (NixOS and nix-darwin) were functions there, each with its own `if` in
`main()`; they are `plugins/kernels`, `plugins/homebrew` and `plugins/home-manager`, moved
without change, and the generator knows none of them by name. Still one command and one press:
`all` runs every plugin that applies, and a plugin for another kind of system is left out
without a word. The generator finds plugins in `plugins/` beside `bin/` (the Nix package passes
`--plugins-dir` for its copy) and in `plugins_dir`, and honours `[plugin.NAME] enabled = false`,
all through `--config` (the button's command has it since `_autocomplete_command()` knows
`CONFIG_FILE`; `autocompleteCommand` in `options.nix` passes the module's `eznix.toml`). A
command named after a plugin runs that one; one that adds to `options.json` runs as `options`,
so the file is never only its share. A plugin that raises is warned about and skipped; one that
calls `ctx.failed()` leaves its file as it was and ends the run with an error, as the kernels
did. **This is an exception to "a plugin needs nothing from the system"**: these three are for
one system each, and have no service, which is what that rule was about. Checked by running the
old and the new generator on the same flakes and comparing the files: the user's nix-darwin
flake (1,204 options, Homebrew's 8,661 formulas and 7,781 casks, identical), and a throwaway
NixOS flake with home-manager 26.05 as a module (29,894 options of which 5,315 home-manager's,
and 20 kernels, identical); also `test_server.py` (`generator_plugins()`), the command's text
evaluated on the darwin template. Not tried: pressing the button in the page, a user plugin on
a real machine, the module's `eznix.toml` read by the generator on NixOS.
The same day the user's ezberry (a flake with the home-manager *input* and not its module)
generated 5,541 home-manager options and typing "home" in Add option offered none:
`optionSearch()` skips an option with a placeholder before its last part, and every one has
`<name>` in the middle, so it relies on the set above them (`home-manager.users`) being
an option, which the system's list has only with the module imported. The plugin now adds that
one entry, and the generator keeps one entry per path (`generate_options()`). Checked by
running `optionSearch()`, lifted out of the page, on ezberry's generated list: 0 results for
"home" before, `home-manager.users` after, and 50 under `home-manager.users.alice.home`.
Not looked at in the page.

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
into browsers or the keychain unless `trustCert` is set; the README gives the command.

With a certificate, plain HTTP on the same port gets a redirect to https (`_Server`,
`_redirect_to_https()`): the first byte of a connection says which it is. The reverse was
built on 2026-10-13 and taken out within the hour (commit `1ad76b6`, reverted): with HTTPS
switched off, https answered by a redirect to http with the certificate left in the state
folder, the page's ping taking a redirect as a reason to reload, and both redirects a 307.
The user had switched HTTPS off in the editor and rebuilt, and the page hung, as did the
app when reopened; with the change "it just makes the app blink when i login". Why was not
found: my guess is a browser that tries https first by itself, which the new answer then
sent back to http, round and round. That hang is therefore still there. A second try the
same day gave HTTPS and plain HTTP a port each (9443 and 9090), the one not in use answering
with a page that said where eznix was and to install the app again (commit `966b08f`, also
reverted): the user found that "doesnt work in a good way either" and chose instead an
application-menu entry made from the configuration (`programs.eznix.enable`, not built
yet), which follows a change of address by a rebuild. The TLS handshake
moved from the listening socket into each connection's thread for that, which also stops a
silent client from holding up `accept()`. Not in `test_server.py`, which has no
`cryptography` to make a certificate with; tried by hand with `nix run . -- --https`.

`trustCert` (off by default, as the user asked; asked again on 2026-10-15 whether HTTPS on
localhost alone should switch it on, and kept off: the authority has no name constraints,
so trusted it could vouch for any site, and a browser's warning still lets the user log in)
adds that authority to the browsers of the
machine eznix runs on: `trustCertScript` in `options.nix`, ported from ezconf's
`installCerts`, which ran as root for a list of users and was on by default. Here it always
runs as the person concerned: a oneshot unit per user on NixOS, the editor's `ExecStartPre`
under home-manager, `sudo -u` in the activation on macOS, where the keychain part needs the
password dialog a rebuild in a real terminal can show. Read the comments there before
touching it; each oddity was found on a real machine.

**Values an option can be chosen from, where its type does not list them, come from
`choices.json`**, written by the generator under the option's path (`write_choices()`):
`{values, expr, free}`, a value a text or `{value, description}`, `expr` for Nix expressions,
`free` for suggestions beside which anything may be typed. The page shows any option found
there as a dropdown, or a list as chips (`choicesFor()`, `nameListFor()`), and knows none by
name. Until 2026-10-12 it did: `isKernelPath()` tested for `boot.kernelPackages` and
`nameListFor()` for `homebrew.brews` and `homebrew.casks`, each with a file of its own
(`kernels.json`, `brews.json`, `casks.json`, which the generator now removes), the two
places the user's rule against naming an option was still broken. Which option a list
belongs to is said where the list comes from, in the plugin that generates it (see "The
generator's plugins"). A new kind of list is an entry there and nothing in the page. Data generated before that day
has no `choices.json`, so those two things are not offered until the generator has run
again. Checked by running the generator for the kernels (a NixOS flake, 12) and for
Homebrew (a Mac, 8,652 formulas and 7,804 casks) and the two lookups on what it wrote; the
user then ran Autocomplete in the test server on a NixOS flake and reported "it works",
without saying what was looked at. On the user's Mac, updated to that commit, `homebrew.casks`
was a plain list until Autocomplete was pressed once, and had its chips again after ("it
works!").

Suggestions are never generated automatically: it is the `eznix-autocomplete` command, run by
the user. Of several configurations it takes the one named like the machine (for home-manager
`user@host` or `user`), else the first; since 2026-10-18, at the user's wish, the first also
when the machine's own entry's options do not evaluate (`pick_options()`), and the options are
evaluated before the plugins and packages so that all three come from the one host. A host
named on the command line has no fallback. Tried on a throwaway flake with a host named like
this Mac that imports a missing file: `options` and `all` fall back, a named host and two
broken ones fail as before. A fallback for `packages` alone was not built.
The suggestions' folder is shared by everyone in `users` on NixOS (2775, no sticky bit), so
the generator never writes or reads there through a link (since 2026-10-18, found in a
review): `.generating` is removed and made with `O_EXCL | O_NOFOLLOW`, a file is written
beside its name under a `mkstemp` name and moved over it, and `choices.json` is read with
`O_NOFOLLOW`. Before, a link another user put at `.generating` (or at the temporary file's
name, the process number) had the generator overwrite and open up the file it pointed at.
In `test_server.py` (`generator_links()`, which fails on the old code); not on NixOS. Options that are not `visible` (how `mkRemovedOptionModule` and
`mkRenamedOptionModule` declare theirs) are left out as the NixOS manual leaves them out,
since 2026-10-15: `programs.eznix.browser` was still offered after its removal, among
1,735 such options of 26,350 on NixOS. The user confirmed the fix on Linux after a rebuild
that brought the new generator, and Autocomplete. Since 2026-10-10 the header has an Autocomplete button for it, on the user's wish,
which only types that command into the terminal (it is part of `terminal-panel/`, so there is
none without a terminal); before that the templates carried it as one of their buttons.
It is there in install mode as well since 2026-10-13 (it was left out there, and the
installer had one of its own in its row, now removed at the user's word).
Its icon turns while the generator runs: the generator leaves `.generating`, with its
process number, where the suggestions go, and the ping says whether that process is there
(`_autocomplete_running()`). Whether the suggestions are *behind* the flake is not shown: a
checksum of `flake.nix` and `flake.lock` was built for it and dropped the same day, since it
misses a module added in any other file, and the user chose a button that is always active.

## Not verified

Run in headless Chrome on 2026-10-11, at the user's request, against throwaway flakes: going
back past a saved rename, a saved folder disable and a saved new folder, and saving again
(the disk came out right each time, the folder staying as described above); the two login
limits, on a server with them shortened to 8 and 40 seconds (the page kept open stayed
logged in, closed for longer than the first limit it came back as the login page, and left
open past the second it went to the login page by itself); stylesheets and scripts answered
304 on a second load, and the page itself once answers said HTTP/1.1, with saving, the
ping and the terminal's socket working over it; the page hidden until the editor is filled; a name, its value and a
heading each centred in a 24px row; the list behaviour.


What has run for real, by the user's reports on 2026-10-09 and no closer than that: all three
modules. nix-darwin on a Mac (services, system-password login, the terminal surviving
rebuilds, HTTPS on localhost with `trustCert` and its keychain dialog, the redirect from
http); NixOS on a real machine ("works cleanly", including `interface` once `certNames` was
set); home-manager on another Linux in a VM, where the terminal's missing environment and
`home.packages` not being a package list were found and fixed. The terminal restart notice
was seen on NixOS and macOS across an update that changed the terminal. The user tested
"all I could" and it works on the three. `trustCert` on NixOS (the per-user units) was tried
by the user on 2026-10-10: the authority deleted from `~/.pki/nssdb` with `certutil -D`, the
unit `eznix-trust-USER` restarted, and `certutil -L` listed it again with `C,,` (their
paste), and the browser, restarted, opened the page without a warning ("yes works"). The home-manager step was tried on
Debian, and on macOS it is confirmed. The Documents button and the System menu, in
the header since 2026-10-10, work by the user's word that day ("the document menu and system
menu works"); which entries of the System menu were used was not said. The points below are
what nobody went through.

- From 2026-10-11, seen only on one side or not at all: the `breeze-light` and both `gnome-*`
  themes against a real desktop (`breeze-dark` and the selection colour of both Breeze themes
  were measured in the user's screenshots of Plasma; the GNOME surfaces were checked against
  libadwaita's `_colors.scss`). The slow reconnect after a rebuild on the user's router came
  back after the DNS lookup at start was removed: the server's log (with `debug`) had the
  browser sending nothing for 46 seconds in the middle of a page load, on a connection it
  had already opened. Connections are reused since then; whether that ends it is for the
  router to show. The phase a stuck request is in (the browser's developer tools, Network,
  Timing) is the evidence still missing. It came back on 2026-10-13, with reused connections:
  by the journal (with `debug`) the server was stopped at 12:53:27 and listening a second
  later, logged no delay of its own, and got nothing until 12:53:52, when three pings came
  in the same second; a restart a quarter of an hour before had taken two seconds. The
  switch restarted `eznix.service` and nothing else. A ping is given up after three seconds
  since then (`PING_TIMEOUT_MS`), at the user's word that seconds on a network mean
  something is wrong; whether that shortens the wait is not known either.
- `flakeWritable` on NixOS, as something that works: a listing the user sent shows the
  permissions it sets (the flake and its files `root:eznix` and group-writable with the
  owner unchanged, setgid and ACL on the folders, `.git`, another dot-folder and
  `.gitignore` untouched). Tried by the user on 2026-10-13, on NixOS: a
  system exported, a line `# test` added to `hardware-configuration.nix` and to
  `flake.nix`, the export imported. The line was still in the hardware file ("#test is
  still in hardware-configuration.nix after import") and gone from the other ("its gone
  from flake.nix"): the import writes the flake there, and keeps the machine's own
  hardware file. (A first try with `touch` showed nothing: an import skips identical
  files.) On 2026-10-15 the user exported, added `groda.txt` to the flake, imported the
  export (the file was gone), and restored the backup the import had taken (it was back);
  on which system was not said.
- The `darwin` template on a machine that had nothing: installing Nix and the first switch
  as the README has them. What else it takes is covered: on 2026-10-15 the template, with
  the name filled in, built against the checkout on 26.05 without switching (its two agents
  there, the terminal's without a store path), refused with `YOUR-USER-NAME` left in, and
  the user runs that version of the module on their own Mac. A fresh Mac in a VM was
  offered and not wanted. (`home` was: on a fresh Debian 13 VM,
  `nix flake init -t`, the name filled in, the password file, the first switch, and it worked
  first time. `nixos` was on 2026-10-12, by a report the user brought: a VM installed from the
  NixOS 26.05 minimal ISO, the README's Quick Start typed as written at commit `f644f75`, all
  of it without an error; login with the system password in the VM's Firefox, the generator
  (27,578 options in 11 s), a save and a rebuild after it. In that test the buttons and the
  terminal in the page were not clicked, the commands behind them were run over SSH and the
  save went through the API, and the machine was not rebooted into the new generation. The
  template's `nixos-unstable` took the 26.05 install to 26.11 on the first rebuild, which is
  why the templates name the stable release since. With that, each of the three was
  evaluated against 26.05 on a Mac with the checkout's eznix, down to the system's or the
  generation's derivation; none was built or installed that way.)
- System-password login on a non-NixOS Linux through nixpkgs' PAM library does not work:
  tried on Debian 13 with home-manager on 2026-10-15 (the user's report): the library reads
  the host's `/etc/pam.d/login`, cannot parse its `@include` lines (Debian's own addition to
  PAM) or load its `pam_selinux.so`, and never reaches `pam_unix`. So the home-manager
  module refuses `users` and asks for `passwordFile` (or `password`), the user's choice the
  same day after it was first only documented ("why do we have that option even if only one
  works"): home-manager on NixOS, where it worked, has the NixOS module for that.
- home-manager as a module inside a NixOS flake (`home-manager.users.<name>`): the generator's
  home-manager plugin was run on a throwaway NixOS flake with home-manager 26.05 as a module on
  2026-10-17 (5,315 options came out, the same as the generator before the plugins); not on a
  real flake of the user's.
