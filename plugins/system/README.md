# system

The **System** button: the whole flake as a zip, out and back in, and backups of it.

## ✨ What it does

- **Export** the flake as a zip
- **Import** a zip over the flake: the files end up exactly as in the zip, except this
  machine's own `hardware-configuration.nix`, which stays
- **Backup** the flake now, and **restore** any backup from the list
- **Import from** a list of places: zips and indexes of systems, on the web or on this
  machine, shown as a menu
- A backup is made by itself before every import and restore

## 📋 Options

```nix
services.eznix.plugins.system = {
  backups = 10;
  exclude = [ ".*" "result" "*.key" ];
  keep    = [ "hardware-configuration.nix" ];
  sources = [
    "https://github.com/me/systems/archive/refs/heads/main.zip"
    { name = "Templates"; url = "https://example.org/systems/index.json"; }
  ];
};
```

| Option | Default | |
|---|---|---|
| `backups` | `5` | how many backups are kept; `0` for none |
| `exclude` | `[ ".*" ]` | what an export leaves out, read like the lines of a `.gitignore` |
| `keep` | `[ "hardware-configuration.nix" ]` | what an import leaves as it is on this machine, read the same way; a restore keeps nothing back |
| `sources` | `[ ]` | where systems can be imported from: an `https` address or a path on this machine, or `{ name, url }` |
| `enabled` | `true` | `false` leaves the plugin out |

## 🌍 Sources

Each source is a heading in the System menu, **Import from NAME**, and the systems in it are
the lines under it, named by their folders. Choosing one imports it as an import of a zip does: the backup first,
this machine's hardware file kept.

- **A zip**: every folder in it that has a `flake.nix` is a system, so one zip can hold
  many, in folders and subfolders. A repository downloaded from GitHub
  (`…/archive/refs/heads/main.zip`) works as it is: the one folder around everything is
  left out of the names.
- **A folder on GitHub**: the address as the browser shows it,
  `https://github.com/OWNER/REPO/tree/BRANCH/PATH`. The zips in it are systems, named by
  their file names, and its folders are listed the same way, down to four levels; a folder
  with no zip below it is left out. The branch is one name without a slash. GitHub allows
  60 such listings an hour without a login, and a listing is kept for ten minutes.
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
  that holds several; `items` is a folder of the menu.

What is imported is built as root at the next rebuild, so a source is only ever named in
the configuration, never typed into the page, and plain `http` is refused (an index on the
web can only lead to `https`). A download is kept for ten minutes, and used again when the
place cannot be reached; the ↻ at the end of a source's heading downloads that source anew.
At most 256 MiB is downloaded.

## 📝 Notes

- An import or a restore writes to disk at once: there is no Save step and no undo, only the
  backup taken just before.
- An import is all or nothing: if eznix may not change one of the files, nothing is changed.
- Only a zip of a system is taken: one with `flake.nix` at its top, as an export has. Any
  other zip is refused and nothing is changed. A repository downloaded as a zip has a folder
  around its files; zip what is inside that folder instead.
- A list of your own for `exclude` replaces the default, so it has to say `".*"` itself to
  keep dot-files and dot-folders out.
- Dot-files in a zip are never imported, whatever `exclude` says.
- A zip of more than 100,000 files, 2 GiB unpacked, or a file over 1 GiB is refused as too big to be a system.
