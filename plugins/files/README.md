# files

Menus of your flake's files, by their kind. Each menu is a button in eznix's tab bar, beside Search; a file
opens in your own editor, in a terminal of its own that is a tab beside the configuration.

## ✨ What it does

- One menu out of the box: **Nix files**, listing the flake's `.nix` files
- A file opens in `$EDITOR` (or nano), or in the editor you name
- More menus as you like, each with its own kinds of file and its own program
- **New file…** asks for a path, which has to end in one of the menu's endings, and opens the editor on it; the editor makes the file when you save, and a folder that is not there yet is made first (the dialog says so as you type); the ✕ on a file's line deletes it
- Leaving the editor closes its tab, and so does the tab's ✕
- An open file slides out of the way when you click outside it, like the terminal

## 🚀 Usage

Nothing to set for the Nix files menu. To choose the editor:

```nix
services.eznix.plugins.files.editor = "vim";
```

It is a plain string, so it can be a program from Nix that is not installed anywhere else:

```nix
services.eznix.plugins.files.editor = lib.getExe pkgs.helix;
```

Menus of your own replace the one there is. Each can have its own program:

```nix
services.eznix.plugins.files = {
  editor = "vim";
  menus = [
    { name = "Nix files"; extensions = [ ".nix" ]; }
    { name = "Notes";     extensions = [ ".md" ".txt" ]; command = lib.getExe pkgs.micro; }
  ];
};
```

In `eznix.toml`, for an eznix run by hand:

```toml
[plugin.files]
editor = "vim"

[[plugin.files.menus]]
name = "Notes"
extensions = [".md", ".txt"]
command = "micro"
```

## 📋 Options

| Option | Default | |
|---|---|---|
| `editor` | `$EDITOR` in your shell, then nano | what a file opens in, for every menu without a `command` |
| `menus` | one: Nix files, `.nix` | the menus; an empty list shows none |
| `menus.*.name` | its extensions | what the button says |
| `menus.*.extensions` | | the files it lists, by how their names end |
| `menus.*.command` | `editor` | what this menu's files open in |
| `auto_hide` | `true` | an open file slides away on a click outside it; the arrow button at the side's top left corner hides and shows it by hand, and stays in view while it is away |
| `exclude` | `[ ".*" ]` | what no menu lists, read like the lines of a `.gitignore` |
| `enabled` | `true` | `false` leaves the plugin out |

## 📝 Notes

- A command is any program that runs in a terminal and takes the file as its last argument.
- It needs eznix's terminal; without one there are no buttons.
- The tab's ✕ ends the editor as closing a terminal window would. An editor like vim keeps
  what was unsaved in its recovery file and offers it the next time the file is opened.
- Deleting a file from a menu is at once and keeps no copy.
- Two kinds of file that should open in different programs go in two menus.
