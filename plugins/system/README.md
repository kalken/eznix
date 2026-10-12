# system

The **System** button: the whole flake as a zip, out and back in, and backups of it.

## ✨ What it does

- **Export** the flake as a zip
- **Import** a zip over the flake: the files end up exactly as in the zip
- **Backup** the flake now, and **restore** any backup from the list
- A backup is made by itself before every import and restore

## 📋 Options

```nix
services.eznix.plugins.system = {
  backups = 10;
  exclude = [ ".*" "result" "*.key" ];
};
```

| Option | Default | |
|---|---|---|
| `backups` | `5` | how many backups are kept; `0` for none |
| `exclude` | `[ ".*" ]` | what an export leaves out, read like the lines of a `.gitignore` |
| `enabled` | `true` | `false` leaves the plugin out |

## 📝 Notes

- An import or a restore writes to disk at once: there is no Save step and no undo, only the
  backup taken just before.
- An import is all or nothing: if eznix may not change one of the files, nothing is changed.
- A list of your own for `exclude` replaces the default, so it has to say `".*"` itself to
  keep dot-files and dot-folders out.
- Dot-files in a zip are never imported, whatever `exclude` says.
