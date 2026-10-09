#!/usr/bin/env python3
"""The flake as a zip, out and back in: what the system plugin does, and the eznix-backup command.

  eznix-backup save                  zip the flake into the backup folder
  eznix-backup save --output FILE    ... or into a file of your own, which is never pruned
  eznix-backup list                  the backups there are, newest first
  eznix-backup restore               pick one from a list and put it back
  eznix-backup restore NAME|FILE     a particular one; --yes skips the question

One file for both, on purpose: the page's buttons (system.py loads this) and the command work on
the same zips in the same folder, <state_dir>/system-backups, so a backup made by either shows up
in the other. The command never goes through the server, and works with the plugin switched off.

Putting a zip back -- restore here, import and restore in the page -- writes straight to disk
and deletes every in-scope file the zip doesn't mention, so the tree ends up matching the zip
exactly instead of merging into what was there. (Import used to be a merge; the surprising case
turned out to be importing your own export and it *not* replacing the tree the way restoring the
same kind of zip does.) The current tree is saved first every time, so the list is mostly a
history of "the state right before the last few destructive writes", plus what `save` put there.
Only the newest `backups` are kept, whoever made them.

Where things are comes from the same eznix.toml the server reads (--config, default
./eznix.toml), or from --flake and --state-dir. Settings, under [plugin.system]:
  backups   how many backups to keep (default 5; 0: none)
  dotfiles  include dot-files and dot-folders in an export (default false)
  exclude   file names to leave out of an export, anywhere in the tree
"""
import argparse
import datetime
import os
import shutil
import sys
import zipfile

PREFIX = 'system-'


class BadZip(ValueError):
    """A zip that can't be put back as it is; nothing was written."""


class Tree:
    """One flake folder and the folder its backups are kept in."""

    def __init__(self, flake, backup_dir, keep=5, dotfiles=False, exclude=()):
        self.flake = os.path.realpath(flake)
        self.backup_dir = backup_dir
        self.keep = int(keep)
        self.skip_dotfiles = not dotfiles
        self.exclude = {str(n) for n in exclude if str(n).strip()}

    def files(self):
        """(absolute path, path in the zip) for every file an export holds. Dot-files and
        dot-folders are left out by default -- .git, .direnv, key material is conventionally
        dot-prefixed, and this is a deliberately blunt way to keep secrets out of a
        downloadable zip. Symlinks are always skipped: `nix build`'s "result" links point into
        /nix/store, and without them this is a plain walk with no cycles."""
        for dirpath, dirnames, filenames in os.walk(self.flake):
            dirnames[:] = [d for d in dirnames
                           if not (self.skip_dotfiles and d.startswith('.'))
                           and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if (self.skip_dotfiles and fn.startswith('.')) or fn in self.exclude or os.path.islink(full):
                    continue
                yield full, os.path.relpath(full, self.flake).replace(os.sep, '/')

    def export(self, dest, reason=''):
        """Zip the tree into dest, a path or a file object. The reason it was made travels in
        the zip's own comment, which is what the lists show."""
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            for full, arcname in self.files():
                zf.write(full, arcname)
            zf.comment = reason.encode()

    def snapshot(self, reason):
        """Zip the current tree into the backup folder and prune to the newest `keep`. Returns
        the backup's name, or None when backups are switched off."""
        if self.keep <= 0:
            return None
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        name, i = f'{PREFIX}{stamp}.zip', 1
        while os.path.exists(os.path.join(self.backup_dir, name)):
            name, i = f'{PREFIX}{stamp}-{i}.zip', i + 1
        self.export(os.path.join(self.backup_dir, name), reason)
        for old in [b['name'] for b in self.listing()][self.keep:]:
            try:
                os.remove(os.path.join(self.backup_dir, old))
            except OSError:
                pass
        return name

    def listing(self):
        """The backups, newest first: name, mtime, size, and -- from the zip itself -- how many
        files it holds and why it was made ('' for one from before reasons were kept)."""
        items = []
        if os.path.isdir(self.backup_dir):
            for name in os.listdir(self.backup_dir):
                if name.startswith(PREFIX) and name.endswith('.zip'):
                    path = os.path.join(self.backup_dir, name)
                    st = os.stat(path)
                    item = {'name': name, 'mtime': st.st_mtime, 'size': st.st_size, 'files': None, 'reason': ''}
                    try:
                        with zipfile.ZipFile(path) as zf:
                            item['files'] = sum(not i.is_dir() for i in zf.infolist())
                            item['reason'] = zf.comment.decode('utf-8', 'replace')
                    except (zipfile.BadZipFile, OSError):
                        pass
                    items.append(item)
        # The name breaks a tie between two made within the same clock tick.
        return sorted(items, key=lambda b: (b['mtime'], b['name']), reverse=True)

    def plan(self, zf):
        """What putting this zip back would do, without doing it: {'write': [(target, entry)],
        'skipped': [names], 'remove': [(path, name)]}. An entry with an empty, '.', '..' or
        dot-prefixed path segment is skipped and reported: that mirrors the export's own
        dot-file rule (a zip built elsewhere can't write into .git or .ssh) and is also what
        stops a path-traversal entry."""
        write, skipped = [], []
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace('\\', '/')
            if any(p in ('', '.', '..') or p.startswith('.') for p in rel.split('/')):
                skipped.append(info.filename)
                continue
            target = os.path.realpath(os.path.join(self.flake, rel))
            if os.path.commonpath([self.flake, target]) != self.flake:
                # Not expected after the check above; abort before writing anything.
                raise BadZip('invalid entry path: ' + info.filename)
            write.append((target, info))
        kept = {os.path.relpath(t, self.flake).replace(os.sep, '/') for t, _ in write}
        return {'write': write, 'skipped': skipped,
                'remove': [(full, arcname) for full, arcname in self.files() if arcname not in kept]}

    def apply(self, zf):
        """Make the tree match the zip. Every entry is checked before any is written."""
        plan = self.plan(zf)
        written = []
        for target, info in plan['write']:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            written.append(os.path.relpath(target, self.flake).replace(os.sep, '/'))
        removed = []
        for full, arcname in plan['remove']:
            try:
                os.remove(full)
                removed.append(arcname)
            except OSError:
                pass
        return {'ok': True, 'written': written, 'skipped': plan['skipped'], 'removed': removed}


# ── The command ───────────────────────────────────────────────────────────────

def _fail(message):
    sys.exit('eznix-backup: ' + message)


def _settings(args):
    """(flake, state_dir, [plugin.system]) the way eznix.py's main() arrives at them: its
    defaults are repeated here, since this file can't import the server."""
    cfg = {}
    config = args.config or ('eznix.toml' if os.path.exists('eznix.toml') else None)
    if config:
        try:
            import tomllib
        except ImportError:
            _fail('reading a config file needs Python 3.11+ (or pass --flake and --state-dir)')
        try:
            with open(config, 'rb') as f:
                cfg = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            _fail(f'{config}: {e}')
    path = lambda p: os.path.abspath(os.path.expanduser(str(p)))
    flake = path(args.flake or cfg.get('flake') or ('/etc/nix-darwin' if sys.platform == 'darwin' else '/etc/nixos'))
    state = path(args.state_dir or cfg.get('state_dir') or '~/.local/state/eznix')
    plugin = (cfg.get('plugin') or {}).get('system') or {}
    return flake, state, plugin if isinstance(plugin, dict) else {}


def _become_owner(state_dir, flake):
    """Run as whoever the backups belong to, and write files the way the editor does.

    An installed eznix keeps its state under an account of its own (NixOS: `eznix`, a folder
    nobody else can read), so there this has to be started with sudo -- and then must not leave
    root's files in the flake, which the editor could no longer save over. So root steps down to
    the owner of the state folder (of the flake, while there is no state folder yet) before
    touching anything. New files are group-writable where the flake folder itself is, which is
    how the NixOS module lets the listed users edit the flake by hand."""
    try:
        owner = os.stat(state_dir if os.path.exists(state_dir) else flake)
    except OSError:
        return
    if os.geteuid() == 0 and owner.st_uid != 0:
        import pwd
        try:
            os.initgroups(pwd.getpwuid(owner.st_uid).pw_name, owner.st_gid)
        except (KeyError, OSError):
            os.setgroups([owner.st_gid])
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)
    try:
        if os.stat(flake).st_mode & 0o020:
            os.umask(0o002)
    except OSError:
        pass


def _when(mtime):
    t, today = datetime.datetime.fromtimestamp(mtime), datetime.date.today()
    day = {0: 'today', 1: 'yesterday'}.get((today - t.date()).days, t.strftime('%Y-%m-%d'))
    return f'{day} {t:%H:%M}'


def _print_listing(tree, items):
    print(f'Backups of {tree.flake}\n')
    rows = [(str(n), _when(b['mtime']), '?' if b['files'] is None else f"{b['files']} files", b['reason'])
            for n, b in enumerate(items, 1)]
    widths = [max(len(r[c]) for r in rows) for c in range(3)]
    for r in rows:
        print('  ' + f'{r[0]:>{widths[0]}}  {r[1]:<{widths[1]}}  {r[2]:>{widths[2]}}  {r[3]}'.rstrip())


def _ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ''


def _choose(tree):
    """The menu: the path of the backup picked, or None."""
    items = tree.listing()
    if not items:
        _fail(f'no backups in {tree.backup_dir}')
    _print_listing(tree, items)
    while True:
        answer = _ask(f'\nRestore which? [1-{len(items)}, Enter to cancel]: ')
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return os.path.join(tree.backup_dir, items[int(answer) - 1]['name'])
        print(f'Not one of 1-{len(items)}.')


def _cmd_save(tree, args):
    if args.output:
        tree.export(args.output, 'saved by hand')
        print(f'Saved {tree.flake} to {args.output}')
        return
    name = tree.snapshot('saved by hand')
    if name is None:
        _fail('backups are switched off ([plugin.system] backups = 0); use --output FILE')
    print(f'Saved {tree.flake} as {name}')


def _cmd_list(tree, args):
    items = tree.listing()
    if not items:
        print(f'No backups in {tree.backup_dir}')
        return
    _print_listing(tree, items)


def _cmd_restore(tree, args):
    interactive = sys.stdin.isatty()
    if args.backup:
        # A file of your own, or the name of one in the backup folder (with or without .zip).
        path = next((p for p in (args.backup, os.path.join(tree.backup_dir, args.backup),
                                 os.path.join(tree.backup_dir, args.backup + '.zip')) if os.path.isfile(p)), None)
        if not path:
            _fail(f'no such backup: {args.backup}')
    elif not interactive:
        _fail('name the backup to restore (see `eznix-backup list`): there is no terminal to ask in')
    else:
        path = _choose(tree)
        if not path:
            print('Nothing restored.')
            return
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        _fail(f'{path}: {e}')
    # The backup being restored may itself be pruned by the snapshot taken below, so it is
    # open before that happens.
    with zf:
        try:
            plan = tree.plan(zf)
        except BadZip as e:
            _fail(str(e))
        print(f"\nThis replaces {len(plan['write'])} files in {tree.flake}"
              + (f" and removes {len(plan['remove'])} that the backup doesn't have:" if plan['remove'] else '.'))
        for _, name in plan['remove'][:20]:
            print('  removed: ' + name)
        if len(plan['remove']) > 20:
            print(f"  ... and {len(plan['remove']) - 20} more")
        if plan['skipped']:
            print(f"{len(plan['skipped'])} entries in it are left out (dot-files): " + ', '.join(plan['skipped'][:5])
                  + (' ...' if len(plan['skipped']) > 5 else ''))
        print('The current state is saved first, so this can be undone.' if tree.keep > 0
              else 'Backups are switched off, so this cannot be undone.')
        if not args.yes:
            if not interactive:
                _fail('add --yes to restore without being asked: there is no terminal to ask in')
            if _ask('Continue? [y/N]: ').lower() not in ('y', 'yes'):
                print('Nothing restored.')
                return
        saved = tree.snapshot('before restore')
        result = tree.apply(zf)
    print(f"Restored: {len(result['written'])} files written, {len(result['removed'])} removed."
          + (f' The state before is {saved}.' if saved else ''))


def main():
    ap = argparse.ArgumentParser(
        prog='eznix-backup', description='Back up the flake eznix edits, or put a backup back.',
        epilog='Backups are shared with the editor: its Restore menu lists the same ones.')
    ap.add_argument('--config', metavar='FILE', help="eznix's config file (default: ./eznix.toml)")
    ap.add_argument('--flake', metavar='DIR', help='the flake')
    ap.add_argument('--state-dir', metavar='DIR', help='where eznix keeps its own data, the backups among it')
    sub = ap.add_subparsers(dest='command', required=True, metavar='save | list | restore')
    p = sub.add_parser('save', help='back the flake up now')
    p.add_argument('--output', metavar='FILE', help='write the zip here instead of into the backup folder')
    sub.add_parser('list', help='the backups there are')
    p = sub.add_parser('restore', help='put a backup back, chosen from a list unless named')
    p.add_argument('backup', nargs='?', metavar='NAME|FILE', help='a backup from the list, or a zip of your own')
    p.add_argument('--yes', action='store_true', help="don't ask before replacing the flake's files")
    args = ap.parse_args()

    flake, state, cfg = _settings(args)
    _become_owner(state, flake)
    if not os.path.isdir(flake):
        _fail(f'no flake in {flake} (--flake, or `flake` in the config file)')
    tree = Tree(flake, os.path.join(state, 'system-backups'), cfg.get('backups', 5),
                cfg.get('dotfiles', False), cfg.get('exclude', []))
    try:
        {'save': _cmd_save, 'list': _cmd_list, 'restore': _cmd_restore}[args.command](tree, args)
    except PermissionError as e:
        _fail(f'{e.filename}: not allowed. An installed eznix keeps its backups under its own account: try sudo.')


if __name__ == '__main__':
    main()
