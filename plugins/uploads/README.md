# uploads

Send a file from your browser to a folder on the machine. Made for a zip of WireGuard keys that
`ezwgen` reads (`ezwgen --source /var/lib/ezwgen/keys.zip`), but it takes any kind of file you list.

## ✨ What it does

- One **Upload** button in the header, like Documents
- Its menu has a line per target of your own, with the endings it takes (its folder shows as a tooltip): press it to choose a file to upload. Under it are the files in that folder, each with a ✕ that deletes it
- A file of the same name is replaced
- Nothing runs as root: eznix writes the file itself, so the folder has to be one it may write in
- The file gets the mode you set (`0600` unless said), before it has any content
- A zip is checked before it is kept: it has to be a zip, and no name in it may lead out of its folder. It is never unpacked

## 🚀 Usage

```nix
services.eznix.plugins.uploads.targets = [
  { name = "WireGuard keys"; dir = "/var/lib/ezwgen"; }
];

# the folder, owned by eznix, closed to everyone else (root reads it anyway)
systemd.tmpfiles.rules = [ "d /var/lib/ezwgen 0700 eznix eznix -" ];
```

In `eznix.toml`, for an eznix run by hand:

```toml
[[plugin.uploads.targets]]
name = "WireGuard keys"
dir = "/var/lib/ezwgen"
```

## 📋 Options

| Option | Default | |
|---|---|---|
| `targets` | none | the folders to upload to; with none, nothing of the plugin is seen |
| `targets.*.name` | its `dir` | the target's heading in the menu |
| `targets.*.dir` | | the folder, as a full path. It has to exist and eznix has to be able to write in it |
| `targets.*.mode` | `"0600"` | the file mode of what is kept, as octal text |
| `targets.*.extensions` | `[ ".zip" ]` | how a file's name may end; anything else is refused |
| `targets.*.max_size` | `16` | the biggest file, in megabytes |
| `enabled` | `true` | `false` leaves the plugin out |
