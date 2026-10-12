"""Server half of the nixfiles plugin: lists the *.nix files in the flake.

  GET  files   every *.nix file, as paths relative to the flake

That is all of it: a file is opened in an editor of the user's own, in a terminal (see
nixfiles.js), which reads and writes it without this. For some hours on 2026-10-12 the plugin
had an editor of its own in the page, and this file read, checked, saved, backed up and
deleted for it; the user chose the terminal's editor over it and had the rest taken out.

Settings ([plugin.nixfiles] in eznix.toml):
  editor    the program a file is opened in: "vim", "nano", "hx"; default: what $EDITOR
            names in the terminal's shell, or nano
  exclude   what not to list, read like the lines of a .gitignore, as eznix's own `exclude`
            is (api.ignore). Default [".*"]: dot-files and dot-folders.
"""
import os


def setup(api):
    base = os.path.realpath(api.flake)
    excluded = api.ignore(api.config.get('exclude', ['.*']))
    # What the page is told: the settings, and where the flake is, which the command that
    # opens a file has to name in full (a shell need not start there).
    api.page = dict(api.config, flake=base)

    def files(req):
        """A symlinked folder or file is skipped, so this can't follow a `result` link into
        /nix/store or loop."""
        names = []
        for root, dirs, filenames in os.walk(base):
            rel = lambda name: os.path.relpath(os.path.join(root, name), base).replace(os.sep, '/')
            dirs[:] = [d for d in dirs if not excluded(rel(d)) and not os.path.islink(os.path.join(root, d))]
            names += [rel(fn) for fn in filenames
                      if fn.endswith('.nix') and not excluded(rel(fn)) and not os.path.islink(os.path.join(root, fn))]
        return {'files': sorted(names)}

    api.get('files', files)
