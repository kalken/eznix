# eznix reference

Everything the [README](README.md) leaves out: adding eznix to a flake you already have, every
option, HTTPS, buttons, plugins and themes.

## Quick start, for those who know Nix

**Try it**, nothing installed:

```sh
nix run github:kalken/eznix -- --flake /path/to/your/flake --password something
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
  listen       = "192.168.1.2";     # this machine's address; HTTPS is then on by itself
  openFirewall = true;              # NixOS
  # interface  = "wg0";             # optional: answer through this network interface only
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

Rebuild, and open eznix on port 9090: `https://192.168.1.2:9090`, or http://localhost:9090.

**No flake yet?** With Nix installed, one of these writes a `flake.nix` and a first settings
file with eznix switched on. Put your user name in that file before the last command.

```sh
# macOS
mkdir -p ~/.config/nix-darwin && cd ~/.config/nix-darwin
nix flake init -t github:kalken/eznix#darwin
sudo nix run nix-darwin -- switch --flake "$HOME/.config/nix-darwin#default"

# NixOS (keeps your configuration.nix)
cd /etc/nixos
sudo nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#nixos
sudo nixos-rebuild switch --flake "/etc/nixos#default"

# Another Linux (home-manager; also put a password in ~/.config/eznix-password)
mkdir -p ~/.config/home-manager && cd ~/.config/home-manager
nix flake init -t github:kalken/eznix#home
nix run home-manager/master -- switch --flake "$HOME/.config/home-manager#default"
```

Everything else is further down: [each system in detail](#adding-it-to-a-flake-you-already-have),
[all options](#options), [HTTPS](#https), [buttons](#buttons), [plugins](#plugins).

## How the configuration is stored

eznix edits `*.json` files in one folder inside your flake (`<flake>/eznix` by default). Each
file is a tab in the editor. With subfolders the tabs are two rows: the folders and the files
beside them on top, and under it the files of the folder you are in. Drag a file onto a
folder to move it there, and a setting onto another file's tab to move it to that file; held
over a folder, the drag brings up that folder's files to drop on. Import the folder once from your
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

An entry is a path inside the folder: a file, or a folder with everything under it.
Dot-folders are always left out.

A value can also be a raw Nix expression (right-click a value), which can use what a Nix
module is given: `pkgs`, `lib`, `config`, `options`, and what your flake passes in
`specialArgs` (often `inputs`). For example `pkgs.hello`, `lib.mkForce 1`,
`config.networking.hostName`. As in any Nix module, an expression cannot read the setting it
is itself part of. Anything can be switched
off without deleting it (right-click, Disable). Nothing is written until you press Save, and
every save keeps the previous version of the file (right-click a tab, Restore).

Importing and exporting files is on right-click too: a tab for one file, a folder for its
files, and the empty part of the tab bar for all of them (Import, Export all). The System
button at the top is the whole flake instead; see [plugins](#plugins).

## Notes on the quick start

- **Without Nix**, `python3 bin/eznix.py --flake DIR --password PW` from a checkout does what
  `nix run` does. Run by hand, eznix and its terminal run as you and keep their data in
  `~/.local/state/eznix`; add `--https` for HTTPS with a certificate eznix makes itself.
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

## Adding it to a flake you already have

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
terminal. See [Running commands as root](#running-commands-as-root).

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

### Options

The common ones, the same in all three modules:

| Option | Default | |
|---|---|---|
| `flake` | `/etc/nixos`, `/etc/nix-darwin`, `~/.config/home-manager` | the flake being edited (`~/` works on macOS and with home-manager) |
| `configDir` | `<flake>/eznix` | the folder of JSON files |
| `exclude` | `[ ]` | paths in it that are not configuration |
| `users` | | who may log in with their system password |
| `session.cookies.days` | | days a login lasts, 400 at most; unset, until the browser is closed |
| `session.cookies.renew` | `false` | count those days from the last visit instead of from the login |
| `password`, `passwordFile` | | log in with one password instead (not on NixOS) |
| `listen`, `port` | `127.0.0.1`, `9090` | where the editor listens |
| `interface` | | a network interface to be reached through, and no other |
| `terminal` | `true` | the terminal panel |
| `buttons` | `[ ]` | command buttons, see below |
| `theme`, `themes` | | see [Themes](#themes) |
| `plugins`, `extraPlugins` | | see [Plugins](#plugins) |
| `enableHttps`, `trustCert`, `certNames`, `cert`, `key` | | see [HTTPS](#https) |

Every option has a description; `nix/options.nix` is the full list. Run by hand, the same
settings go in an `eznix.toml` (`example/eznix.example.toml` shows all of them).

## Buttons

A button in the terminal bar types a command into the terminal. Set them in the editor itself,
under `services.eznix.buttons` in any of your files, and they appear straight away:

```json
{ "services": { "eznix": { "buttons": [
  { "label": "Rebuild", "command": "sudo nixos-rebuild switch", "save_first": true },
  { "label": "Update",  "command": "nix flake update", "menu": "Flake" }
] } } }
```

A button with `save_first` saves any unsaved changes before it runs its command; the small
Save icon on it is greyed until there is something to save. Buttons with the same
`menu` become one dropdown.

## Suggestions

The option and package suggestions are generated from your own flake, so they match exactly
what your configuration can set. The **Autocomplete** button at the top generates them: it
runs this in the terminal, where you can follow it:

```sh
eznix-autocomplete
```

The open page picks the new data up by itself. Press it again after updating the flake. The
button's icon turns while the suggestions are being generated, and the button is only there
when eznix has a terminal.

The command the modules install already knows your flake. It is also a package of its own,
usable on any flake: `eznix-autocomplete --flake DIR --output DIR` (`--type nixos`, `darwin` or
`home` when it can't tell).

## Running commands as root

Nothing in eznix is root, so a command that needs it asks through `sudo`. How much it asks is
up to your sudo setup:

- **Ask every time** (the default). sudo asks for your password in the terminal and remembers
  it for a few minutes.
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

## Not typing passwords all the time

There are two passwords involved, and each has its own setting.

**Logging in to eznix.** By default a login lasts until the browser is closed. To stay
logged in longer, give it a number of days, and have every visit start the count again:

```nix
services.eznix.session.cookies = { days = 30; renew = true; };
```

400 days is the most a browser allows. Without `renew` the days count from the login.

**`sudo` in the terminal.** By default it asks again after a few minutes. To be asked once
per login session instead, for one user (NixOS and nix-darwin):

```nix
security.sudo.extraConfig = "Defaults:alice timestamp_timeout=-1";
```

To never be asked for the rebuild itself, see
[Running commands as root](#running-commands-as-root) above (on macOS the command there is
`/run/current-system/sw/bin/darwin-rebuild`). Both make the machine easier to take over for
anyone who gets to your eznix login, so they suit a machine only you can reach.

## Plugins

Some features are plugins: a folder of page files, and optionally server code, that eznix
loads when it starts. A plugin is something that needs nothing from the system eznix runs on,
so it works the same everywhere and can be left out. Three ship with it:

| Plugin | |
|---|---|
| `system` | the System button: back the whole flake up, restore a backup, import a zip over it, export it as one |
| `documents` | the Documents button: read the flake's Markdown files beside the editor |
| `password` | log in with one configured password |

Leave one out, or change its settings, by name:

```nix
services.eznix.plugins = {
  documents.enabled = false;
  system.backups    = 10;
};
```

To write your own, make a folder with a `plugin.json` and add it with
`services.eznix.extraPlugins.NAME = ./folder;` (or `plugins_dir` in `eznix.toml`):

```json
{ "name": "hello", "scripts": ["hello.js"], "styles": ["hello.css"], "server": "hello.py" }
```

The scripts run in the page, after eznix's own, and can add buttons and react to events
(listed at the top of the script in `webroot/index.html`, under "Plugins"). The optional
server file adds what the plugin answers under `/api/v1/plugin/NAME/` (see `PluginApi` in
`bin/eznix.py`). The shipped plugins in `webroot/plugins/` are the examples; `documents` is
the smallest complete one.

**A plugin runs with everything eznix can do**, in the page and on the machine. Install one
only if you would run it as a program.

Nobody outside eznix depends on the plugin interface yet, so it may still change.

## Themes

Pick one with the swatches in the status bar; `theme` sets what a browser starts with.
Built in: `nixos`, `dark`, `gruvbox`, `osx-dark`, `osx-light`, and `osx`, which follows the
light or dark appearance of the system the browser runs on.

### Your own themes

A theme is one CSS file of variables, and only needs the ones it changes:

```nix
services.eznix.themes.mine = ./mine.css;
```

(or a `themes_dir` folder of `<name>.css` files in `eznix.toml`). [THEMES.md](THEMES.md)
explains the variables and what to keep to.

## HTTPS

On `localhost` eznix serves plain HTTP, which browsers treat as secure. For anything else it
serves HTTPS with a certificate it makes itself, signed by an authority of its own that is
kept in its state folder. Four options cover it:

| Option | Default | |
|---|---|---|
| `enableHttps` | on when `listen` isn't this machine | serve HTTPS; set it for HTTPS on `localhost` too. eznix makes the certificate unless you give `cert` and `key` |
| `trustCert` | `false` | have the browsers on this machine trust it, so they don't warn |
| `certNames` | `[ ]` | the host names and addresses you open eznix by |
| `interface` | | be reached through one network interface only |

```nix
# HTTPS on this machine, no warning in its browsers:
services.eznix = { enableHttps = true; trustCert = true; };

# Reached from other computers, by this address:
services.eznix = { listen = "0.0.0.0"; certNames = [ "192.168.1.2" ]; };
```

**`trustCert`** adds the authority, at each rebuild, to the certificate lists of Chrome,
Chromium, Brave and Firefox for the people eznix runs for. On macOS it goes into the
keychain, which asks for your password once: run that rebuild in a terminal of your own, not
in eznix's panel. A browser that is open may need a restart to notice.

**`certNames`** is required when eznix listens on every address: `listen = "0.0.0.0"`, which
is also what `interface` alone gives. It can't know then what you will type in the browser,
and without the name the certificate doesn't match and saving is refused. The rebuild stops
and says so. A specific `listen` address is included by itself, with or without `interface`.

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

## Development

```sh
python3 bin/eznix.py --flake DIR --password pw   # run from the checkout
python3 test/test_server.py                      # server and plugin tests
```

[CLAUDE.md](CLAUDE.md) describes how the code is put together.
