"""Server half of the files plugin: lists the flake's files for each of the menus it is set up
with.

  GET  files   for each menu, in the order they are configured: its files, as paths relative
               to the flake; and the flake's folders, which the path of a new file is
               completed from

  POST delete?name=N   removes one of those files

A file is opened by a program of the user's own, in a terminal (see files.js), which reads
and writes it without this. Deleting is the one thing done here, for the cross each file
has in its menu: only a file that a menu lists, at once, with no copy kept.

Settings ([plugin.files] in eznix.toml):
  menus     a list; unless set, one menu, "Nix files", of the .nix files (an empty list:
            none, and nothing of the plugin is seen). Each entry is a button in the header:
              name        what the button says: "Nix files"
              extensions  the files it lists, by how their names end: [".nix"]
              command     what a file is opened with, the file's path being put behind it;
                          default: what $EDITOR names in the terminal's shell, or nano
  exclude   what no menu lists, read like the lines of a .gitignore, as eznix's own `exclude`
            is (api.ignore). Default [".*"]: dot-files and dot-folders.

It was a plugin for Nix files alone, `nixfiles`, with one `editor`, for some hours on
2026-10-12; the user asked for the general thing instead: any kinds of file, each in a menu
with a name, each with its own command. What there is with nothing set went from that one
menu to none and back to it within the hour, at the user's word each time.
"""
import os

DEFAULT_MENUS = [{'name': 'Nix files', 'extensions': ['.nix']}]


def setup(api):
    base = os.path.realpath(api.flake)
    excluded = api.ignore(api.config.get('exclude', ['.*']))
    menus = []
    for entry in api.config.get('menus', DEFAULT_MENUS):
        if not isinstance(entry, dict):
            continue
        endings = [str(e) for e in entry.get('extensions', []) if str(e)]
        if endings:
            menus.append({'name': str(entry.get('name') or ', '.join(endings)), 'extensions': endings,
                          'command': str(entry.get('command') or '')})
    # What the page is told: the menus, and where the flake is, which the command that opens
    # a file has to name in full (a shell need not start there).
    api.page = {'menus': menus, 'flake': base}

    def files(req):
        """A symlinked folder or file is skipped, so this can't follow a `result` link into
        /nix/store or loop."""
        found, folders = [[] for _ in menus], []
        for root, dirs, filenames in os.walk(base):
            rel = lambda name: os.path.relpath(os.path.join(root, name), base).replace(os.sep, '/')
            dirs[:] = [d for d in dirs if not excluded(rel(d)) and not os.path.islink(os.path.join(root, d))]
            folders += [rel(d) for d in dirs]
            for fn in filenames:
                if excluded(rel(fn)) or os.path.islink(os.path.join(root, fn)):
                    continue
                for n, menu in enumerate(menus):
                    if fn.endswith(tuple(menu['extensions'])):
                        found[n].append(rel(fn))
        return {'menus': [sorted(names) for names in found], 'folders': sorted(folders)}

    def delete(req):
        name = req.query.get('name', '')
        parts = name.replace('\\', '/').split('/')
        full = os.path.realpath(os.path.join(base, name))
        if (os.path.isabs(name) or any(p in ('', '.', '..') for p in parts) or excluded(name)
                or not any(name.endswith(tuple(menu['extensions'])) for menu in menus)
                or os.path.commonpath([base, full]) != base or os.path.islink(os.path.join(base, name))
                or not os.path.isfile(full)):
            raise api.Error(400, 'not a file of these menus')
        try:
            os.remove(full)
        except PermissionError:
            raise api.Error(403, 'eznix may not delete ' + name)
        return {'deleted': name}

    api.get('files', files)
    api.post('delete', delete)
