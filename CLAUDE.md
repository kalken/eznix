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
| `bin/eznix-autocomplete.py` | generates the suggestions (`nix eval` over the flake) |
| `webroot/index.html`, `style.css` | the page: one script, no modules |
| `webroot/theme-*.css` | themes: variables only (see `THEMES.md`) |
| `webroot/terminal-panel/` | the terminal's part of the page, with xterm.js |
| `plugins/NAME/` | the shipped plugins: `documents`, `files`, `system`, `password`, each with its page files, its server file and a `README.md` (they were in `webroot/plugins/` until 2026-10-12) |
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
would let any port of the protected host through. `/logout` is a GET and is not
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
server on that address could not either, so it has not been seen answering.
It is IPv4 only: the sockets are `AF_INET`, and an IPv6 address in `listenAddresses` is
left out as one that cannot be listened on.
Tried on a Mac: the default, `lo` with a real interface, a real one alone, the empty list,
a missing interface beside `lo` and alone, and with addresses; the NixOS module evaluated
for the same. On Linux by the user's word the same day, on two NixOS machines rebuilt to it: the
router, with `interfaces = [ "lan" ]` and opened as `ezbox.lan` (a name eznix added by
itself), and a desktop on the default `[ "lo" ]` ("both machines seems to work"). Not yet
seen there: two interfaces at once, which is where two sockets share a port by being tied
to different interfaces, and an interface that is missing.

**Reached from elsewhere, what eznix cannot know goes in `certNames`, by hand.** What it
can know it takes by itself since 2026-10-12: the machine's host name (`hostNames` from the
NixOS and nix-darwin modules: the name, with its domain, and as `NAME.local`; home-manager
has none to give) and the addresses in `listenAddresses`. eznix
doesn't know what will be typed in the browser, so the certificate names only localhost and
a save to any other name is refused until it is listed. A save to a plain address is not
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
advanced" can change it). The number is in each `templates/*/flake.nix`, in `flake.nix` and
in the README's first-switch commands for the Mac and other Linux, and has to be raised by
hand when a release comes out, in May and November. There is no `flake.lock` in the
repository, also by the user's choice ("i dont want to update the lock-file manually"), so
`nix flake init -t` prints a harmless "not writing modified lock file". The one thing to fill in is
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
- The indent is `--indent-step` (2ch) per level and nothing else. A foldable section's
  arrow is part of its heading's text, two characters wide, so its options start under its
  name. Counting the arrows of the sections around a row into its indent was tried and
  taken out.
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
The bar's buttons and Add keep the cursor in the field, since the field's blur hides the bar.
Tried by the user in the test server that day, on `services.samba.settings.global` ("that
works!"): the type chosen from the bar, and Add pressed with no type chosen.

**Sections start out folded from a level**, `collapseLevel` (`collapse_level`): a number, a
top-level section being 1; not set (null), the default, nothing is folded
(`SECTIONS_LEVEL`, `_sectionStartsOpen()`). Until 2026-10-12 the setting was `sections`,
collapsed or expanded, collapsed by default, with the level fixed at 3, the first level
that could be folded then: levels 1 and 2, the cards and the boxes in them, had no arrow
until the user asked for those to fold too the same day, by a click on the name and
without an arrowhead (`.foldable` on every section; `.nest-arrow` stays the mark of level
3 and below, which have the arrowhead).
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
what a zip can do other than by its paths (its size, say), and anything in the page.

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
used. A shell named after the file is started on `mkdir -p DIR && exec COMMAND 'path'`, so
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
offered under its path field.
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

**Values an option can be chosen from, where its type does not list them, come from
`choices.json`**, written by the generator under the option's path (`write_choices()`):
`{values, expr, free}`, a value a text or `{value, description}`, `expr` for Nix expressions,
`free` for suggestions beside which anything may be typed. The page shows any option found
there as a dropdown, or a list as chips (`choicesFor()`, `nameListFor()`), and knows none by
name. Until 2026-10-12 it did: `isKernelPath()` tested for `boot.kernelPackages` and
`nameListFor()` for `homebrew.brews` and `homebrew.casks`, each with a file of its own
(`kernels.json`, `brews.json`, `casks.json`, which the generator now removes), the two
places the user's rule against naming an option was still broken. Which option a list
belongs to is said in the generator, which has to know where the list comes from anyway. A
new kind of list is an entry there and nothing in the page. Data generated before that day
has no `choices.json`, so those two things are not offered until the generator has run
again. Checked by running the generator for the kernels (a NixOS flake, 12) and for
Homebrew (a Mac, 8,652 formulas and 7,804 casks) and the two lookups on what it wrote; the
user then ran Autocomplete in the test server on a NixOS flake and reported "it works",
without saying what was looked at. On the user's Mac, updated to that commit, `homebrew.casks`
was a plain list until Autocomplete was pressed once, and had its chips again after ("it
works!").

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
  `.gitignore` untouched), but the user has not tried writing the flake through the editor,
  and no system import has been done there.
- The `darwin` template on a machine that had nothing. (`home` was: on a fresh Debian 13 VM,
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
- System-password login on a non-NixOS Linux through nixpkgs' PAM library (the template
  there uses a password file).
- home-manager as a module inside a NixOS flake (`home-manager.users.<name>`): the generator
  has a path for its options, untried on a real flake.
