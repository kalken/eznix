# home-manager

Suggestions for home-manager's options when it is used as a module of a NixOS or nix-darwin
system: `home-manager.users.<name>.*`.

## ✨ What it is for

- Completing and describing the options of home-manager inside the system's own JSON files
- Needs a home-manager input in the flake (found by what it provides, so any name will do);
  without one it adds nothing (the generator says so with -v or when asked for by name)
- Also offers `home-manager.users` itself, which typing `home` finds: the system's own options
  have it only when home-manager's NixOS or nix-darwin module is imported. Setting any of these
  needs that module in the flake (`home-manager.nixosModules.home-manager`, or
  `darwinModules.home-manager`); the input alone is not enough
- A standalone home-manager configuration needs no plugin: its own options already are
  home-manager's

## 🚀 Usage

Nothing to do: it is part of what the **Autocomplete** button generates, and adds its options
to `options.json`. It builds a throwaway home-manager evaluation with a placeholder user and
reads its options, so no real user is needed. Leave it out with
`services.eznix.plugins.home-manager.enabled = false;`.

It has no page files. It is a plugin of the suggestions' generator (`eznix-autocomplete`, see
"Plugins" in `bin/eznix-autocomplete.py`).

## 📋 Options

| Option | Default | |
|---|---|---|
| `enabled` | `true` | `false` leaves it out |
