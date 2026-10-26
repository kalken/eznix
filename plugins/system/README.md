# system

The **System** button: the whole flake as a zip, out and back in, and backups of it.

## ✨ What it does

- **Export** the flake as a zip: all its files and folders, but what `protect` and `exclude` name
- **Import** a zip over the flake: the files and folders end up exactly as in the zip, and
  only what `protect` names is left as it is: no old files stay. The question
  before it lists what is left alone and what is removed
- **Backup** the flake now, and **restore** any backup from the list
- **Import from** a list of places: zips, folders and indexes of systems, on the web or on
  this machine, shown as headings in the menu
- A backup is made by itself before every import and restore

## 📋 Options

```nix
services.eznix.plugins.system = {
  backups = 10;
  protect = [ ".git" ".direnv" ];
  exclude = [ "hardware-configuration.nix" "*.key" ];
  sources = [
    "https://github.com/me/systems/archive/refs/heads/main.zip"
    { name = "Import from Templates"; url = "https://example.org/systems/index.json"; }
    { name = "Start from"; url = "${pkgs.eznix}/share/eznix/templates"; add_only = true; }
  ];
};
```

| Option | Default | |
|---|---|---|
| `backups` | `5` | how many backups are kept; `0` for none |
| `protect` | `[ ".git" ]` | what belongs to this machine and is never touched: not exported, not backed up, never written or removed by an import or restore. Read like the lines of a `.gitignore` |
| `exclude` | `[ "hardware-configuration.nix" ]` | what an export leaves out: what is this machine's own and should not travel. An import does not look at it (see below) |
| `generate` | none | a list of `{ file, command }`: files to make when an import leaves them missing, each with the command that makes it (see below). An entry needs both, or it is ignored: there are no defaults, since it has to fit every platform and a template sets it |
| `open` | none | files to open after an import, relative to the flake: set in a template's own configuration (see below) |
| `sources` | `[ ]` | where systems can be imported from: an `https` address or a path on this machine, or `{ name, url, add_only }`: `name` is the heading in the menu, `add_only` adds files and removes none |
| `enabled` | `true` | `false` leaves the plugin out |

## 🌍 Sources

Each source is a heading in the System menu, below Restore, titled by the `name` of its
entry exactly as you write it (**Import from ezinstall**, **Start from**, …; with no name,
one made from the address), and the systems in it are the lines under it, named by their
folders. The ↻ at its end downloads the source again.
Choosing a system imports it as an import of a zip does: the backup first, and what
only what `protect` names left as it is.

With `add_only = true` on the entry, choosing a system only adds its files over the flake
and removes none, so it can start a flake that already has files of its own that the
system doesn't hold (the NixOS template, which imports the installer's `configuration.nix`).
The question then says "Start from …" in place of "Import …".

- **A zip**: every folder in it that has a `flake.nix` is a system, so one zip can hold
  many, in folders and subfolders. A repository downloaded from GitHub
  (`…/archive/refs/heads/main.zip`) works as it is: the one folder around everything is
  left out of the names.
- **A folder on this machine**: every folder under it that has a `flake.nix` is a system
  (a dot-folder is not searched). `${pkgs.eznix}/share/eznix/templates` is the starting flakes eznix
  ships: `nixos`, `darwin` and `home`.
- **A folder on GitHub**: the address as the browser shows it,
  `https://github.com/OWNER/REPO/tree/BRANCH/PATH`. The zips in it are systems, named by
  their file names, and its folders are listed the same way, down to four levels; a folder
  with no zip below it is left out. The branch is one name without a slash. GitHub allows
  60 such listings an hour without a login, and a listing is kept for ten minutes.
  A `NAME.json` beside `NAME.zip` describes it, and is not a system itself:

  ```json
  { "name": "Router", "description": "A NixOS router with DHCP, DNS and a firewall." }
  ```

  Both are optional (`description` is cut to 500 characters). The name replaces the file's
  name in the list, and the description is shown under it and in the question before an
  import. A file that cannot be read is ignored. The zip itself is not changed, so nothing
  of it lands in the flake.
- **An index**: a JSON file that lists systems, for a menu of your own making:

  ```json
  { "name": "Our systems", "items": [
    { "name": "Desktops", "items": [
      { "name": "Gaming", "url": "gaming.zip", "description": "Steam and the rest" }
    ] },
    { "name": "Router", "url": "https://example.org/all.zip", "path": "router" },
    { "url": "more/index.json" }
  ] }
  ```

  `url` is a zip or another index, relative to this one; `path` picks one folder of a zip
  that holds several (`""` for a zip that is one system). An entry with a `path` is listed as
  it says and its zip is not downloaded until it is chosen, so an index of many systems costs
  one request; one without it is downloaded to see what is in it; `items` is a folder of the menu; `info` is a description file as above
  (relative to the index), for a `description` you would rather keep beside the zip.

What is imported is built as root at the next rebuild, so a source is only ever named in
the configuration, never typed into the page, and plain `http` is refused (an index on the
web can only lead to `https`). A download is kept for ten minutes, and used again when the
place cannot be reached; the ↻ at the end of a source's heading downloads that source anew.
At most 256 MiB is downloaded.

## 🔧 Files to make

Before an import is done (an upload, a source), the page asks the server what it would do, with
nothing written, and shows it under the question: a zip without a `flake.nix` at its top (it
is still imported if you say so), and the files of `generate` that will be missing afterwards.
A file that is there already, or one the zip brings, is not made.

Each entry is a file and the command that makes it:

```json
"generate": [
  { "file": "hardware-configuration.nix",
    "command": "sudo sh -c 'nixos-generate-config --show-hardware-config --no-filesystems > hardware-configuration.nix'" }
]
```

The question shows the command of each file that will be missing, and after the import they are
typed into the terminal, one after the other, each only if the one before worked (`sudo` asks
there). The terminal starts in the flake's folder, so a relative file name lands next to
`flake.nix`.

An import or a restore that changes anything removes the suggestions, which were of the system
that was there. The **Autocomplete** button is then marked until they are generated for the
new one; press it once the commands above have finished.

The list is the zip's own, uploaded or from a source: it is in the JSON files of its
configuration folder, at `services.eznix.plugins.system.generate`, so a system says how a
machine gets its files. That is what the NixOS template does for the hardware file; without
`--no-filesystems` the disks mounted now are included. Only when the zip has none is the setting
of the running configuration used. Nothing runs without your yes: every command is shown in the
question before the import.

## 📖 Files to open

A template can name files to be opened once it is imported, a README that says what to do
next, say. The list is in the JSON files of its configuration folder:

```json
"services": { "eznix": { "plugins": { "system": { "open": [ "README.md" ] } } } }
```

After the import each file that is there is opened with what the page has for its kind: a
`.md` file in Documents, a file with the endings of a menu of the files plugin in that menu's
program, one of the editor's own JSON files as its tab. It is taken from any zip, uploaded or
from a source, since opening a file runs nothing the zip chose. Set in the running
configuration it does nothing.

## 🔎 Suggestions

Nix itself knows plugin settings as one option, "attribute set of attribute set of anything", so
the plugin adds its own to the suggestions when Autocomplete is pressed: `backups`, `exclude`,
`sources`, `generate` (with `file` and `command`, marked as required for an entry), `open` and
`enabled`, each with its description. It is help in the editor only: Nix accepts any value
there. Press Autocomplete once after updating eznix to get them.

## 📝 Notes

- An import or a restore writes to disk at once: there is no Save step and no undo, only the
  backup taken just before.
- An import is all or nothing: if eznix may not change one of the files, nothing is changed.
- Only a zip of a system is taken: one with `flake.nix` at its top, as an export has. Any
  other zip is refused and nothing is changed. A repository downloaded as a zip has a folder
  around its files; zip what is inside that folder instead.
- **Two lists.** `protect` is this machine's and is never exported, backed up, written or
  removed. `exclude` is only for export: what is this machine's own (its hardware file) and
  should not travel.
- An import replaces the whole system: the folder ends up exactly like the zip, files and
  folders (an empty folder too), dot-files included. Whatever the zip holds is written, and
  everything it doesn't hold is removed, but what `protect` names (a path of the zip that it
  names is skipped). No old files are left. What the new system needs and doesn't bring, such
  as the machine's hardware file, its `generate` makes. The question before the import lists
  what is left alone and what is removed, so you can stop it.
- A backup holds everything but what `protect` names, so every file an import removes is in
  the backup taken just before it.
- A restore is the same: the folder ends up exactly like the backup, but what `protect` names.
- A list of your own replaces the default, so `exclude` has to name the hardware file itself
  if it is to stay out. Dot-files such as `.env` are in exports and backups unless one of the
  lists names them, and backups can be read by every user in `users` on NixOS.
- A zip of more than 100,000 files, 2 GiB unpacked, or a file over 1 GiB is refused as too big to be a system.
