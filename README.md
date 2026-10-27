# eznix

Change the settings of a Nix system in your browser, instead of editing files by hand. It
works on NixOS, on a Mac (nix-darwin) and on other Linux (home-manager). No build step, no
framework: just Python and a browser.

## ✨ Features

- Edit a NixOS, nix-darwin or home-manager configuration in a web page, with suggestions for options and packages taken from your own flake
- The configuration is split over files and folders of your choosing, each a tab, merged by Nix when you rebuild
- Nothing is written until you save; undo and redo, and the earlier versions of every file kept to go back to
- Search (Ctrl+F) across all files: type words from an option, a value or a file name, in any order; each result says which file it is in
- A terminal in the page, with buttons and menus of your own for rebuilding and anything else; drag its edge, or a side panel's, to size it
- Nothing runs as root: a rebuild goes through `sudo` in that terminal
- Log in with your system password or a password of its own; HTTPS with a certificate eznix makes itself
- Back up, restore, export and import the whole flake, and read its `.md` files beside the editor
- Open the flake's other files in the page too, `.nix` or any kind you list, in your own editor (vim, nano, …) in a terminal beside the configuration
- An entry in the application menu, made from the configuration (`programs.eznix`)
- Themes: NixOS blue, gruvbox, and OS X, KDE Breeze and GNOME, each light or dark with the system; or your own

## 🚀 Quick Start

You need Nix. NixOS has it. On a Mac or another Linux, install it first, with either
[Determinate Nix](https://docs.determinate.systems/determinate-nix/) or the
[official installer](https://nixos.org/download); both work. Then copy the lines for your
system into a terminal.

The lines below work in one folder: `/etc/nixos` on NixOS, `~/.config/nix-darwin` on a Mac,
`~/.config/home-manager` on other Linux. If that folder already exists, make a copy of it
first. On NixOS it always exists:

```sh
sudo cp -a /etc/nixos /etc/nixos.backup
```

If the folder already has a `flake.nix`, the template stops with "refusing to overwrite" and
changes nothing. Add eznix to your own flake by hand instead:
[Install it in a flake you have](#-for-those-who-know-nix).

**NixOS** (your `configuration.nix` is kept as it is)

```sh
cd /etc/nixos
sudo nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#nixos
sudo sed -i "s/YOUR-USER-NAME/$USER/" eznix/system.json
sudo nixos-rebuild switch --flake "/etc/nixos#default"
```

To move your `configuration.nix` into the editor afterwards, see
[Migrating from configuration.nix](#-migrating-from-configurationnix).

**Mac**

```sh
mkdir -p ~/.config/nix-darwin && cd ~/.config/nix-darwin
nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#darwin
sed -i '' "s/YOUR-USER-NAME/$USER/" eznix/system.json
sudo nix --extra-experimental-features 'nix-command flakes' run nix-darwin/nix-darwin-26.05#darwin-rebuild -- switch --flake "$HOME/.config/nix-darwin#default"
```

**Other Linux**

```sh
mkdir -p ~/.config/home-manager && cd ~/.config/home-manager
nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#home
sed -i "s/YOUR-USER-NAME/$USER/g" eznix/home.json
echo "a-password-of-your-own" > ~/.config/eznix-password && chmod 600 ~/.config/eznix-password
nix --extra-experimental-features 'nix-command flakes' run home-manager/release-26.05 -- switch --flake "$HOME/.config/home-manager#default"
```

The last line takes a few minutes the first time. When it is done, open
http://localhost:9090 in a browser on that computer and log in with your user name and your
usual password (on other Linux: the password you chose above).

Then, in the page:

1. Press **Autocomplete** at the top once, and wait for it to finish. eznix can then
   suggest settings and programs as you type.
2. Change what you want. To add a setting, right-click in the page, choose **Add option…**
   and type its name.
3. Press **Create Generation** at the bottom. It saves your changes and asks for your password
   in the terminal there; they are in effect when it finishes.

Nothing on your computer changes until that last step. The button at the top left saves
without rebuilding.

The `flake.nix` you got builds on the current stable release, 26.05. If you would rather
have the newest packages, the comment at its top names what to put there instead.

## ⚡ For those who know Nix

**Try it**, nothing installed:

```sh
nix run --no-write-lock-file github:kalken/eznix -- --flake /path/to/your/flake --password something
```

Open http://localhost:9090 and log in as yourself with that password.

**Install it** in a flake you have. In `flake.nix`:

```nix
inputs.eznix.url = "github:kalken/eznix";

# in the modules of your system:
modules = [
  ./configuration.nix
  eznix.nixosModules.default        # darwinModules.default on macOS, homeModules.default for home-manager
  (eznix.lib.jsonDir ./eznix)       # the settings eznix saves, as part of your configuration
];
```

In `configuration.nix`, one of these two.

Used from other computers:

```nix
services.eznix = {
  enable       = true;
  users        = [ "alice" ];       # put your user name here (NixOS: who may log in,
                                    # with their system password)
  interfaces   = [ "lo" "enp1s0" ]; # this machine itself and that network; HTTPS is then on by itself
  openFirewall = true;              # NixOS
};
```

Used on the machine itself:

```nix
services.eznix = {
  enable = true;
  users  = [ "alice" ];             # put your user name here (NixOS: who may log in,
                                    # with their system password)
  # Optional: HTTPS on localhost too, and its browsers trusting the certificate.
  # enableHttps = true;
  # trustCert    = true;
};
```

With home-manager, `passwordFile = "/home/alice/.config/eznix-password";` in place of `users`
(see [Other Linux](#other-linux-home-manager)).

Rebuild, and open eznix on port 9090: `https://192.168.1.2:9090`, or http://localhost:9090.

**No flake yet?** The [Quick Start](#-quick-start) writes one for you.

## 📑 How the configuration is stored

eznix edits `*.json` files in one folder inside your flake (`<flake>/eznix` by default). Each
file is a tab in the editor. With subfolders the tabs are two rows: the folders and the files
beside them on top, and under it the files of the folder you are in. Drag a file onto a
folder to move it there, and a setting onto another file's tab to move it to that file; held
over a folder, the drag brings up that folder's files to drop on.

Tabs stand by name, the folders first. To move one, give it an `order` under
`services.eznix.paths`, by its path as the tabs show it: a folder's name, or a file's path
without `.json`. A number, lowest first, where a tab without one counts as 0. So -10 puts it
first in its row and 10 last.

```json
{ "services": { "eznix": { "paths": { "network": { "order": -10 }, "network/wan": { "order": -10 } } } } }
```

Import the folder once from your
configuration, through the function eznix's flake provides:

```nix
imports = [ (inputs.eznix.lib.jsonDir ./eznix) ];
```

It merges every JSON file in the folder, the same way Nix merges modules. eznix puts nothing
of its own in there. If the flake is a git repository, the folder has to be tracked by git
for Nix to see it.

The folder can be any folder (`configDir`), also one that holds other things. JSON in it
that is not configuration has to be left out, in both places: for the build, and for the
editor, which would otherwise show it as a tab.

```nix
imports = [ (inputs.eznix.lib.jsonDir { dir = ./.; exclude = [ "package.json" "vendor" ]; }) ];

services.eznix.configDir = "/etc/nixos";
services.eznix.exclude   = [ "package.json" "vendor" ];
```

An entry is read like a line of a `.gitignore`:

- `vendor` leaves out a file or folder of that name wherever it is, a folder with everything under it
- `/vendor` or `sub/old.json` counts from the top of the folder only
- `*`, `?` and `[a-z]` are wildcards within a name (`*.lock.json`), `**` stands for any folders (`**/generated`)
- `!keep.json` takes back what an earlier entry left out; it can't bring back something inside a folder that is left out

Dot-folders are always left out.

A setting the suggestions don't know can be added all the same, as free-form settings
often need: type its whole name in **Add option…**, press Enter and pick what kind of value
it is.

**Add option…** puts the new option where you right-clicked: after the option on that line,
first when you click above the first one (on a section's heading, say), and last below the
last one.

A set whose entries are plain values or lists, such as `networking.hosts` (an address and
its names), has a last row of its own: type a new entry's name where it says **Add item…**
and press Enter. A click on an entry's name there renames it.

In a list of objects (`services.eznix.buttons`, say), right-click an object and choose **Add
item like…** for a new one with the same settings, all of them empty.

A value can also be a raw Nix expression (right-click a value), which can use what a Nix
module is given: `pkgs`, `lib`, `config`, `options`, and what your flake passes in
`specialArgs` (often `inputs`). For example `pkgs.hello`, `lib.mkForce 1`,
`config.networking.hostName`. As in any Nix module, an expression cannot read the setting it
is itself part of. Anything can be switched
off without deleting it (right-click, Disable). Nothing is written until you press Save, and
every save keeps the previous version of the file (right-click a tab, Restore; Backup there
keeps a copy of the file as it is on disk right now).

To take one section or option to another computer, right-click it and choose Copy: it is
also put on the clipboard as text, which you paste into Import in the editor there.

Importing and exporting files is on right-click too: a tab for one file, a folder for its
files, and the empty part of the tab bar for all of them (Import, Export all). The System
button at the top is the whole flake instead; see [plugins](#-plugins).

While the flake's folder has no `flake.nix`, as on an installer before a system is imported,
nothing would read the files, so the editor offers no new file, folder or import. Files that
are there anyway open as usual, with a notice in the corner that they are not used.

## 🧩 Adding it to a flake you already have

Add it to the inputs, then use the module for your system.

```nix
inputs.eznix.url = "github:kalken/eznix";
```

### NixOS

```nix
imports = [ inputs.eznix.nixosModules.default (inputs.eznix.lib.jsonDir ./eznix) ];

services.eznix = {
  enable = true;
  users  = [ "alice" ];
};
```

The `eznix` folder doesn't have to exist yet; the first rebuild creates it.

The editor runs as its own account (`eznix`), never as root. Everyone in `users` logs in with
their own system password and gets a terminal of their own, running as them.

The flake is shared between the service and those users through the `eznix` group: its files
and folders become writable by that group, while their owner stays who it was (usually root)
and dot-folders such as `.git` are left alone. That is what lets the editor import or restore
a whole flake, and lets the people in `users` edit `flake.nix` without `sudo`. With
`flakeWritable = false` only the JSON folder is shared, and an import that would change
anything outside it is refused whole, naming the files.

Rebuilding from the terminal needs root, so it goes through `sudo` like it would in any
terminal. See [Running commands as root](#-running-commands-as-root).

### macOS (nix-darwin)

```nix
imports = [ inputs.eznix.darwinModules.default (inputs.eznix.lib.jsonDir ./eznix) ];

system.primaryUser = "alice";
services.eznix.enable = true;
```

The editor and its terminal run as the primary user while they are logged in. Log in with
your macOS password.

### Other Linux (home-manager)

```nix
imports = [ inputs.eznix.homeModules.default (inputs.eznix.lib.jsonDir ./eznix) ];

services.eznix = {
  enable       = true;
  passwordFile = "/home/alice/.config/eznix-password";
};
```

Two user services, running as you. It edits your home-manager flake
(`~/.config/home-manager`), and rebuilding is `home-manager switch`, with no root involved.
You log in with the password in `passwordFile`; system passwords (`users`) are for NixOS and
macOS. Write the path as a string, as above, and not as a path in the flake (`./password`):
a flake is copied into the Nix store, where every account can read it. A secret from
sops-nix or agenix works too (`config.sops.secrets.NAME.path`).

## 🔁 Migrating from configuration.nix

After the Quick Start, or after adding eznix to your own flake, your old configuration is
still in `configuration.nix`, used beside what you set in eznix. To move it into the editor:

1. Right-click the empty part of the tab bar and choose **Import…**. Press **Load file** and
   pick your `configuration.nix`, or paste its contents.
2. Take the `imports = [ … ];` line out of the text: eznix refuses it, because a JSON file
   cannot import other files. Remember what it listed.
3. Under **Import into**, type a name for the new file, for example `configuration`, and
   press **Import**. Settings that are not plain values are kept as Nix expressions.
4. In `flake.nix`, take `./configuration.nix` out of the list of modules, and put what the
   `imports` line listed there in its place (usually `./hardware-configuration.nix`).
5. Press **Create Generation**.

Do steps 1 to 4 before rebuilding: with the same setting in both places Nix reports a
conflict. Afterwards you can spread the settings over more files by dragging them onto
other tabs. Keep `configuration.nix` until the rebuild has worked.

## 🔘 Buttons

A button in the terminal bar types a command into the terminal. Set them in the editor itself,
under `services.eznix.buttons` in any of your files, and they appear straight away:

```json
{ "services": { "eznix": { "buttons": [
  { "label": "Rebuild", "command": "sudo nixos-rebuild switch", "save_first": true,
    "description": "Builds the system and switches to it" },
  { "label": "Update",  "command": "nix flake update", "menu": "Flake" }
] } } }
```

Resting the pointer on a button shows its command, and above it the `description`, if you
gave it one: what the button does, in your own words.

A button with `save_first` saves any unsaved changes before it runs its command; the small
Save icon on it is greyed until there is something to save. Buttons with the same
`menu` become one dropdown.

Buttons stand in the order they are found: file by file, by path, and each list as written.
A menu stands where its first button is found. To move a menu, give it an `order` under
`services.eznix.menus`, by its name: a number, lowest first, where plain buttons and menus
without one count as 0. So 10 puts the menu after everything else, wherever its buttons are
defined, and -10 before. `separator` draws a dividing line beside it: `"before"`, `"after"`
or `"both"`.

```json
{ "services": { "eznix": { "menus": { "Flake": { "order": 10, "separator": "before" } } } } }
```

A button can have a `separator` too: a line beside it in the bar, or across the list when it
is in a menu. Two lines never end up next to each other, and there is none at either end.

Set in Nix instead, in a `.nix` file of your own, a button needs `static = true`, and so does a
menu's entry under `services.eznix.menus`: those are built into eznix's configuration, where
the editor's files are read as they are.

## 🔄 Suggestions

The option and package suggestions are generated from your own flake, so they match exactly
what your configuration can set. Until they are generated, the **Autocomplete** button is
marked, in the accent colour with a dot on its corner. The **Autocomplete** button at the top generates them: it
runs this in the terminal, where you can follow it:

```sh
eznix-autocomplete
```

The open page picks the new data up by itself. Press it again after updating the flake,
and once after updating eznix past 2026-10-12: the kernels and Homebrew's names are kept in
another file since then, and are not offered until it has been written. The
button's icon turns while the suggestions are being generated, and the button is only there
when eznix has a terminal.

The command the modules install already knows your flake. It is also a package of its own,
usable on any flake: `eznix-autocomplete --flake DIR --output DIR` (`--type nixos`, `darwin` or
`home` when it can't tell).

In a flake with several configurations it uses the one named like this machine, and the
first one when none is, or when that one's options cannot be evaluated (a
`hardware-configuration.nix` that is not in the flake, say). Name one to use that and no
other: `eznix-autocomplete all NAME`.

## 🔑 Running commands as root

Nothing in eznix is root, so a command that needs it asks through `sudo`. How much it asks is
up to your sudo setup:

- **Ask every time** (the default). sudo asks for your password in the terminal and remembers
  it for 5 minutes.
- **Allow the rebuild without a password**, on NixOS:

  ```nix
  security.sudo.extraRules = [ {
    users    = [ "alice" ];
    commands = [ { command = "/run/current-system/sw/bin/nixos-rebuild"; options = [ "NOPASSWD" ]; } ];
  } ];
  ```

- **Allow everything without a password**: `security.sudo.wheelNeedsPassword = false;` on
  NixOS, for members of `wheel`. Anyone who can log into eznix as such a user is then
  effectively root.

## 🔐 Not typing passwords all the time

There are two passwords involved, and each has its own setting.

**Logging in to eznix.** By default a login ends when the page has been closed for 15
minutes (the browser quit, the computer asleep), and a day after logging in at the latest.
To stay logged in longer, give it a number of days, and have every visit start the count
again:

```nix
services.eznix.session = { days = 30; renew = true; };
```

400 days is the most a browser allows. Without `renew` the days count from the login.

**`sudo` in the terminal.** By default it asks again 5 minutes after it was last used. To
make that longer for one user (NixOS and nix-darwin), give it a number of minutes:

```nix
security.sudo.extraConfig = "Defaults:alice timestamp_timeout=30";
```

`-1` in place of the number asks once and not again while that terminal lives. It counts per
terminal, so a shell opened another way, over SSH for one, is not loosened by it.

To never be asked at all, on NixOS, for everyone in the group `wheel`:

```nix
security.sudo.wheelNeedsPassword = false;
```

To never be asked for the rebuild only, see
[Running commands as root](#-running-commands-as-root) above (on macOS the command there is
`/run/current-system/sw/bin/darwin-rebuild`). All of these make the machine easier to take
over for anyone who gets to your eznix login, and the first one makes that login root
outright, so they suit a machine only you can reach.

## 🔌 Plugins

Some features are plugins: a folder of page files, and optionally server code, that eznix
loads when it starts. A plugin is something that needs nothing from the system eznix runs on,
so it works the same everywhere and can be left out. Seven ship with it:

| Plugin | |
|---|---|
| [`system`](plugins/system/README.md) | the System button: back the whole flake up, restore a backup, import a zip over it, or a system from a list of places on the web, export it as one |
| [`documents`](plugins/documents/README.md) | the Documents button: read the flake's Markdown files beside the editor |
| [`files`](plugins/files/README.md) | the Nix files button, and others you set up: open the flake's files of a kind in your own editor, in a terminal beside the configuration |
| [`password`](plugins/password/README.md) | log in with one configured password |
| [`kernels`](plugins/kernels/README.md) | suggestions: the kernels `boot.kernelPackages` can be set to (NixOS) |
| [`homebrew`](plugins/homebrew/README.md) | suggestions: the names `homebrew.brews` and `homebrew.casks` can be filled in from (nix-darwin) |
| [`home-manager`](plugins/home-manager/README.md) | suggestions: home-manager's options inside a NixOS or nix-darwin system |

The last three have no page files: they add to what the **Autocomplete** button generates, each
only on the kind of system it is for.

Each has a page of its own, linked above, with what it does and every setting. Leave one
out, or change its settings, by name:

```nix
services.eznix.plugins = {
  documents.enabled = false;
  system.backups    = 10;
  files.editor      = "vim";      # what the Nix files open in; default: $EDITOR
};
```

To write your own, make a folder with a `plugin.json` and add it with
`services.eznix.extraPlugins.NAME = ./folder;` (or `plugins_dir` in `eznix.toml`):

```json
{ "name": "hello", "scripts": ["hello.js"], "styles": ["hello.css"], "server": "hello.py" }
```

A plugin can also add to the suggestions: name a file as `"autocomplete"` in `plugin.json`, with a
`generate(ctx)` that returns `{"options": [...], "choices": {...}}` (see "Plugins" in
`bin/eznix-autocomplete.py`; the three above are the examples). It runs when Autocomplete is
pressed, and `SYSTEMS = ("nixos", ...)` in the file limits it to those kinds of system.

The scripts run in the page, after eznix's own, and can add buttons and react to events
(listed at the top of the script in `webroot/index.html`, under "Plugins"). The optional
server file adds what the plugin answers under `/api/v1/plugin/NAME/` (see `PluginApi` in
`bin/eznix.py`). The shipped plugins in `plugins/` are the examples; `documents` is
the smallest complete one.

**A plugin runs with everything eznix can do**, in the page and on the machine. Install one
only if you would run it as a program.

Nobody outside eznix depends on the plugin interface yet, so it may still change.

## 🎨 Themes

Pick one with the swatches in the status bar; `theme` sets what a browser starts with.
Not set, it is the theme of the system eznix runs on where that is known: `osx` on macOS,
and on NixOS `breeze` with Plasma or `gnome` with GNOME, when that is the only desktop
enabled. Otherwise it is `nixos`, the blue one.
A pair of a light and a dark theme has one swatch, which follows the system; to have one of
the two regardless, name it in `theme`.
Built in: `nixos`, `gruvbox`, and three that follow the light or dark appearance of the system
the browser runs on: `osx`, `breeze` (KDE Plasma's colours) and `gnome` (Adwaita). Each of
those is a pair, `osx-dark` and `osx-light` and so on.

The colours are the theme's and nothing else's: Dark Reader is told to leave the page alone,
and so is a browser's own forced dark mode. Other extensions that restyle pages can't be
kept out.

The tab's icon is the logo in the theme's colours. So is the icon of the page installed as
an app, in the colours of the theme set as `theme`; after changing that, the browser
fetches the new icon by itself, and it shows once the app has been closed and opened again.

### Your own themes

A theme is one CSS file of variables, and only needs the ones it changes:

```nix
services.eznix.themes.mine = ./mine.css;
```

(or a `themes_dir` folder of `<name>.css` files in `eznix.toml`). [THEMES.md](THEMES.md)
explains the variables and what to keep to.

## 🔒 HTTPS

On `localhost` eznix serves plain HTTP, which browsers treat as secure. For anything else it
serves HTTPS with a certificate it makes itself, signed by an authority of its own that is
kept in its state folder. Four options cover it:

| Option | Default | |
|---|---|---|
| `enableHttps` | on when eznix is reached from elsewhere | serve HTTPS; set it for HTTPS on `localhost` too. eznix makes the certificate unless you give `cert` and `key` |
| `trustCert` | `false` | have the browsers on this machine trust it, so they don't warn |
| `certNames` | `[ ]` | more host names and addresses you open eznix by, beside the machine's own name |
| `interfaces` | `[ "lo" ]` | the network interfaces eznix is reached through, and no others; `"lo"` is the machine itself |

```nix
# HTTPS on this machine, no warning in its browsers:
services.eznix = { enableHttps = true; trustCert = true; };

# Reached from other computers, with a certificate that names what you open it by:
services.eznix = { interfaces = [ "lo" "enp1s0" ]; certNames = [ "192.168.1.2" ]; };
```

**`trustCert`** adds the authority, at each rebuild, to the certificate lists of Chrome,
Chromium, Brave and Firefox for the people eznix runs for. On macOS it goes into the
keychain, which asks for your password once: run that rebuild in a terminal of your own, not
in eznix's panel. A browser that is open may need a restart to notice.

**`interfaces`** says where eznix is reached, as dnsmasq and Samba say it: a list of network
interfaces, `[ "lo" ]` (this machine itself) unless you add to it. No address is set, so it
suits a machine that gets its address from DHCP:

```nix
services.eznix = {
  interfaces   = [ "lo" "enp1s0" ];     # this machine itself, and that network
  openFirewall = true;                  # NixOS: on enp1s0 alone
};
```

Open it by the machine's address, `https://192.168.1.2:9090`, or on the machine itself as
`https://localhost:9090`. eznix itself takes nothing that arrives through another interface,
whatever the firewall says, which is what you want on a router.

- `openFirewall` has to be told where: it needs `interfaces` or `listenAddresses` to be set,
  or the rebuild stops. With only addresses it opens the port on every interface.
- leave `"lo"` out and the machine itself is shut out too
- an empty list, `[ ]`, is every interface, for where their names are not known
- a name that is not an interface of the machine is left out, with a line in the log, and
  the rest still work
- `listenAddresses = [ "192.168.1.2" ];` narrows it further, to those addresses of the interfaces
- `listenAddresses` with no `interfaces` set is those addresses and nothing else, through
  any interface: add `"127.0.0.1"` to keep `localhost`

**`certNames`** is for when eznix is reached from elsewhere by something it can't know by
itself. The machine's host name is in the certificate without being listed (also with its
domain, and as `NAME.local`), on NixOS and macOS, and so are the addresses in
`listenAddresses`. List anything else you open it by, and the certificate matches. Without it:

- opened by its address (`https://192.168.1.2:9090`), eznix works, and the browser warns
  about the certificate each time. That is all a machine with an address from DHCP needs.
- opened by a host name that is not listed, eznix answers with nothing but a line saying
  which name to add. That keeps out a website that points its own name at your machine.

An address in `listenAddresses` is included by itself.

With HTTPS on, an `http://` address on the same port is answered with a redirect to
`https://`.

### A browser on another computer

`trustCert` only reaches browsers on the machine eznix runs on. Anywhere else, the browser
warns until you add the authority there yourself, once. The login page has a link to download
it (`eznix-HOSTNAME-ca.pem`); then, for your own user:

```sh
# macOS
security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db eznix-HOSTNAME-ca.pem

# Linux: Chrome, Chromium, Brave (certutil is in nixpkgs#nssTools)
certutil -d sql:$HOME/.pki/nssdb -A -t C,, -n "eznix (HOSTNAME)" -i eznix-HOSTNAME-ca.pem
```

Firefox keeps its own list: Settings, Certificates, View Certificates, Import. The same
commands serve an eznix run by hand with `--https`, whose authority is
`~/.local/state/eznix/ca.pem`.

### Your own certificate, or a proxy

Use `cert` and `key` instead for a certificate of your own, or put eznix behind a reverse
proxy and add the proxy's host name to `hosts`.

Saving and the terminal are refused unless the request comes from eznix's own page, at the
address the browser sent it to. A proxy has to pass the browser's `Host` header on for that
(nginx: `proxy_set_header Host $http_host;`). If it can't, add the page's address to `hosts`
as well, in full: `hosts = ["nix.example.org", "https://nix.example.org"]`.

Failed logins are limited per address (5 in 5 minutes). Behind a proxy everyone arrives from
the proxy's address, so one person's failed tries would lock the others out: list the proxy in
`trustedProxies` (`trusted_proxies` in `eznix.toml`) and set `X-Forwarded-For` in it
(nginx: `proxy_set_header X-Forwarded-For $remote_addr;`). The header is read only from a
connection that comes from a listed proxy.

## 📌 In the application menu

On NixOS and with home-manager, eznix can be an entry in the application menu, with
eznix's icon, that opens it in the default browser. Its address comes from the
configuration, so a changed port or HTTPS is followed at the next rebuild.

```nix
programs.eznix = {
  enable = true;
  # url  = "https://router.lan:9090/";   # another machine's editor instead of this one's
};
```

For the editors of other machines, add an entry each. Every entry is shown with its
address, as "eznix (https://router.lan:9090)":

```nix
programs.eznix.apps = {
  router = "https://router.lan:9090/";
  pi     = "https://pi.lan:9090/";
};
```

Neither needs `services.eznix` on the machine itself. For a window of its own, install
eznix from the browser's menu instead ("Install page as app"); such an app belongs to the
address it was installed from, so it has to be installed again after switching HTTPS on or
off or changing the port.

## 📋 Options

The common ones, the same in all three modules:

| Option | Default | Description |
|---|---|---|
| `flake` | `/etc/nixos`, `/etc/nix-darwin`, `~/.config/home-manager` | the flake being edited (`~/` works on macOS and with home-manager) |
| `configDir` | `<flake>/eznix` | the folder of JSON files |
| `exclude` | `[ ]` | what in it is not configuration, as in a `.gitignore` (see [How the configuration is stored](#-how-the-configuration-is-stored)) |
| `users` | | who may log in with their system password (NixOS and macOS) |
| `session.days` | | days a login lasts, 400 at most; unset, until the page has been closed for 15 minutes, and a day at most |
| `session.renew` | `false` | count those days from the last visit instead of from the login |
| `password`, `passwordFile` | | log in with one password instead (not on NixOS; the way in with home-manager) |
| `port` | `9090` | the editor's port |
| `listenAddresses` | `[ ]` | addresses to answer on, and no others: through any interface when `interfaces` is not set, else of those the interfaces have; empty: all |
| `interfaces` | `[ "lo" ]`, or `[ ]` with `listenAddresses` set | the network interfaces eznix is reached through, and no others (`"lo"`: the machine itself, `[ ]`: any); see [HTTPS](#-https) |
| `openFirewall` | `false` | NixOS: open the port in the firewall, where `interfaces` or `listenAddresses` say; see [HTTPS](#-https) |
| `paths` | `{ }` | where a tab stands, see [How the configuration is stored](#-how-the-configuration-is-stored) |
| `terminal` | `true` | the terminal panel |
| `terminalAutoHide` | `true` | hide the open terminal on a click outside it |
| `terminalHiddenLines` | `1` | lines of the terminal's latest output still shown above its buttons while it is hidden, to follow a rebuild from the editor (`0`: none, only the buttons) |
| `buttons`, `menus` | | command buttons and their menus, see [Buttons](#-buttons) |
| `theme`, `themes` | | see [Themes](#-themes) |
| `plugins`, `extraPlugins` | | see [Plugins](#-plugins) |
| `enableHttps`, `trustCert`, `certNames`, `cert`, `key` | | see [HTTPS](#-https) |
| `collapseLevel` | | the level from which sections start out folded in the editor, a top-level section being 1 (`1` folds them all, `4` what is inside `services.openssh.settings`); not set, nothing is folded |
| `arrowLevel` | `3` | the level from which an open section has an arrow in front of its name, a top-level section being 1 (`0`: none); a folded section always has one |
| `compactLevel` | `1` | the level from which a section that holds only one sub-section is shown as one with it, under both names (`a.b`), a top-level section being 1 (`0`: never) |
| `indent` | `2` | how far each level of nesting is indented in the editor, in characters |
| `debug` | `false` | log what is only worth knowing while looking into something: every request and what took long, and in the browser's console what the page does; the log is otherwise starts, logins and errors |

Beside `services.eznix` there is `programs.eznix` (`enable`, `url`, `apps`): see [In the application menu](#-in-the-application-menu).

Every option has a description; `nix/options.nix` is the full list. Run by hand, the same
settings go in an `eznix.toml` (`example/eznix.example.toml` shows all of them).

## 📝 Notes

- **Do not expose eznix's port to the internet.** Whoever logs in gets a shell and can change
  the configuration of the whole system. Keep it to the machine itself and a network you
  trust.
- **Without Nix**, `python3 bin/eznix.py --flake DIR --password PW` from a checkout does what
  `nix run` does. Run by hand, eznix and its terminal run as you and keep their data in
  `~/.local/state/eznix`; add `--https` for HTTPS with a certificate eznix makes itself.
- **eznix needs a flake.** Systems configured without one (only `/etc/nixos/configuration.nix`
  and channels) are not supported: the suggestions are read from the flake's
  `nixosConfigurations` (or `darwinConfigurations`, `homeConfigurations`), and a system export
  is the flake as a whole, so without one there is nothing for either to work on. The NixOS
  Quick Start turns such a system into a flake without losing anything: the template keeps
  your `configuration.nix` and adds eznix beside it (see
  [Migrating from configuration.nix](#-migrating-from-configurationnix) to move it into the
  editor later).
- **The configuration is called `default`** in the templates, so there is no host name to
  fill in; that is why the rebuild commands end in `#default`. The quotes around the flake
  path matter in some shells (zsh with `extendedglob`), where a bare `#` is part of a pattern.
- **On macOS the template sets `nix.enable = false`**: Nix itself is left to whatever
  installed it. Determinate Nix requires that (nix-darwin refuses to activate otherwise), and
  it works with the official installer too. Set it to `true` there if you want nix-darwin to
  manage Nix and its settings.
- **Each template comes with** these buttons: List Generations (the earlier versions of the
  system you can go back to), Create Generation (rebuilds and switches to what you saved),
  Clear Generations (deletes the earlier ones and frees the disk space; there is no going
  back to them afterwards) and Update Flake.

## 🛠 Development

```sh
python3 bin/eznix.py --flake DIR --password pw   # run from the checkout
python3 test/test_server.py                      # server and plugin tests
```

[CLAUDE.md](CLAUDE.md) describes how the code is put together.

_Change the settings of a Nix system in your browser._
