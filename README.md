# eznix

Edit a Nix configuration in the browser. eznix shows the options of a NixOS, nix-darwin or
home-manager configuration as a form, with suggestions for options and packages, and saves what
you set as plain JSON files that your flake imports. A terminal panel underneath runs the
rebuild.

No build step and no dependencies beyond Python: one server file, one page, and a few plugins.

## Try it

```sh
nix run github:kalken/eznix -- --flake /path/to/your/flake --password something
```

Then open http://localhost:9090 and log in as yourself with that password. Without Nix,
`python3 bin/eznix.py --flake DIR --password PW` from a checkout does the same.

Run this way, eznix and its terminal both run as you. It keeps its own data in
`~/.local/state/eznix`.

## How the configuration is stored

eznix edits `*.json` files in one folder inside your flake (`<flake>/eznix` by default). Each
file is a tab in the editor; subfolders group them. Import the folder once from your
configuration:

```nix
imports = [ ./eznix ];
```

The `default.nix` eznix puts in that folder merges every JSON file in it, the same way Nix
merges modules. If the flake is a git repository, the folder has to be tracked by git for Nix
to see it.

A value can also be a raw Nix expression (right-click a value), and anything can be switched
off without deleting it (right-click, Disable). Nothing is written until you press Save, and
every save keeps the previous version of the file (right-click a tab, Restore).

## Installing it

Add eznix to your flake's inputs, then use the module for your system.

```nix
inputs.eznix.url = "github:kalken/eznix";
```

### NixOS

```nix
imports = [ inputs.eznix.nixosModules.default ];

services.eznix = {
  enable = true;
  users  = [ "alice" ];
};
```

The editor runs as its own account (`eznix`), never as root. Everyone in `users` logs in with
their own system password and gets a terminal of their own, running as them. The JSON folder
is shared between the service and those users through the `eznix` group.

Rebuilding from the terminal needs root, so it goes through `sudo` like it would in any
terminal. See [Running commands as root](#running-commands-as-root).

### macOS (nix-darwin)

```nix
imports = [ inputs.eznix.darwinModules.default ];

system.primaryUser = "alice";
services.eznix.enable = true;
```

The editor and its terminal run as the primary user while they are logged in. Log in with
your macOS password.

### Other Linux (home-manager)

```nix
imports = [ inputs.eznix.homeModules.default ];

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
| `flake` | `/etc/nixos`, `/etc/nix-darwin`, `~/.config/home-manager` | the flake being edited |
| `configDir` | `<flake>/eznix` | the folder of JSON files |
| `users` | | who may log in with their system password |
| `password`, `passwordFile` | | log in with one password instead (not on NixOS) |
| `listen`, `port` | `127.0.0.1`, `9090` | where the editor listens |
| `terminal` | `true` | the terminal panel |
| `buttons` | `[ ]` | command buttons, see below |
| `theme`, `themes` | | see [Themes](#themes) |
| `plugins`, `extraPlugins` | | see [Plugins](#plugins) |
| `generateCert`, `cert`, `key` | | see [HTTPS](#https) |

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

`save_first` makes a button unavailable while there are unsaved changes. Buttons with the same
`menu` become one dropdown.

## Suggestions

The option and package suggestions are generated from your own flake, so they match exactly
what your configuration can set. Generate them from the terminal:

```sh
eznix-autocomplete
```

The open page picks the new data up by itself. Run it again after updating the flake. It is
worth a button:

```json
{ "label": "Suggestions", "command": "eznix-autocomplete" }
```

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

## Plugins

Some features are plugins: a folder of page files, and optionally server code, that eznix
loads when it starts. A plugin is something that needs nothing from the system eznix runs on,
so it works the same everywhere and can be left out. Three ship with it:

| Plugin | |
|---|---|
| `system` | export the whole flake as a zip, import one over it, restore an automatic backup |
| `documents` | read the flake's Markdown files beside the editor |
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

On `localhost` eznix serves plain HTTP, which browsers treat as secure. When `listen` is any
other address, the modules turn on `generateCert`: eznix makes a certificate signed by a local
authority of its own. Browsers warn until that authority is trusted; the login page has a link
to download it, and you add it to the browser or system once. On macOS:

```sh
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.pem
```

Use `cert` and `key` instead for a certificate of your own, or put eznix behind a reverse
proxy and add the proxy's host name to `hosts`.

## Development

```sh
python3 bin/eznix.py --flake DIR --password pw   # run from the checkout
python3 test/test_server.py                      # server and plugin tests
```

[CLAUDE.md](CLAUDE.md) describes how the code is put together.
