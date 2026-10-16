# documents

The **Documents** button: read the Markdown files of your flake beside the configuration.

## ✨ What it does

- Lists every `.md` file in the flake
- Opens each as a tab on the side, shown as a page: headings, lists, tables, code
- A link to another document of the flake opens that document
- HTML written in a document is shown as text, and a link or image takes only `http(s)`, `mailto` and plain paths
- What was open is open again after a reload
- An open document slides out of the way when you click outside it, like the terminal

## 📋 Options

| Option | Default | |
|---|---|---|
| `auto_hide` | `true` | an open document slides away on a click outside it; the arrow button at the side's top left corner hides and shows it by hand |
| `enabled` | `true` | `false` leaves the plugin out |

```nix
services.eznix.plugins.documents.enabled = false;
```

## 📝 Notes

- It only reads. To change a document, give the `files` plugin a menu for `.md`.
- Dot-files and dot-folders are not listed.
- The button is only there when the flake has a document.
