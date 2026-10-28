# homebrew

Offers the names `homebrew.brews` and `homebrew.casks` can be filled in from, as chips in the
editor.

## ✨ What it is for

- Picking formulas and casks that exist instead of typing them from memory
- Each with its description from Homebrew, beside it in the list and on a chip under the
  pointer (the formulas and casks of Homebrew itself; a tap's come without)
- Also what the taps in `homebrew.taps` provide, written as `tap/name`
- nix-darwin only, and only where `brew` is installed: without it nothing is written and
  whatever was generated before is left alone

## 🚀 Usage

Nothing to do: it is part of what the **Autocomplete** button generates. A tap just added to
the configuration shows its names after the next rebuild, since only an installed tap can be
listed. Leave it out with `services.eznix.plugins.homebrew.enabled = false;`.

It has no page files. It is a plugin of the suggestions' generator (`eznix-autocomplete`, see
"Plugins" in `bin/eznix-autocomplete.py`), which asks the local `brew` and writes the names to
`choices.json`.

## 📋 Options

| Option | Default | |
|---|---|---|
| `enabled` | `true` | `false` leaves it out |
