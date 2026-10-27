# nixedit

Nix expressions in the editor typed as in a text editor: completion and indenting. Without it
an expression is a plain text field.

## ✨ What it does

- **Package names and options**: `pkgs.` and `config.` followed by a letter or more list the
  packages and the options that start so (from the suggestions **Autocomplete** made)
- **Settings inside a set**: a section turned into an expression (right-click, Convert to Nix)
  completes the options under it by name, and so does every set in it, at any depth:
  `openPorts = [ { por` offers what an entry of `openPorts` has
- **Written out to the value**: a setting taken from the list is written up to its value, by its
  type, the cursor where the value goes: `port = "|";`, `interfaces = [ | ];`, a set opened on a
  line of its own, `enable = |;`
- **Indenting**: a new line keeps the indent of the one before, two spaces more after `{`, `[`,
  `(` or `=`; Enter between `{` and `}` puts each on a line of its own; a closing bracket typed
  on an empty line takes a step back. Shift+Enter is a plain new line

## ⌨️ Keys

| Key | |
|---|---|
| a letter | opens the list, once a name has a letter typed |
| Ctrl+Space | opens the list, also with nothing typed |
| Up, Down | choose |
| Enter | takes the one chosen |
| Tab | takes the one chosen, or the first |
| Escape, Left, Right, Home, End | close the list |

Every change it makes goes through the browser's own undo.

## 📋 Options

```nix
services.eznix.plugins.nixedit.enabled = false;
```

| Option | Default | |
|---|---|---|
| `enabled` | `true` | `false` leaves the plugin out: expressions are plain text fields |

## 📝 Notes

- Only the dotted name before the cursor and the sets and lists around it are read: names
  from `let`, `with` and a function's arguments are not known.
- The suggestions come from **Autocomplete**; until it has run there is nothing to complete.
