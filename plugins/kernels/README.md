# kernels

Offers the kernels `boot.kernelPackages` can be set to, as a dropdown in the editor.

## ✨ What it is for

- Choosing a kernel by name instead of typing `pkgs.linuxPackages_...`
- NixOS only: a nix-darwin or home-manager configuration has no kernel to choose

## 🚀 Usage

Nothing to do: it is part of what the **Autocomplete** button generates, and the dropdown
appears once that has run. Leave it out with `services.eznix.plugins.kernels.enabled = false;`.

It has no page files. It is a plugin of the suggestions' generator (`eznix-autocomplete`, see
"Plugins" in `bin/eznix-autocomplete.py`), which reads the kernels from the flake's own
`pkgs` and writes them to `choices.json`.

## 📋 Options

| Option | Default | |
|---|---|---|
| `enabled` | `true` | `false` leaves it out |
