"""Server half of the system plugin: the whole flake as a zip, out and back in.

  GET  export           download the flake as a zip
  POST import           replace the flake's files with an uploaded zip's
  GET  backups          the backups, newest first
  POST backup           make one now
  POST restore?name=N   replace the flake's files with a backup's

Import and restore are the same operation on a zip from two places. Both write straight to
disk, and both delete every in-scope file the zip doesn't mention, so the tree ends up matching
the zip exactly instead of merging into what was there. (Import used to be a merge; the
surprising case turned out to be importing your own export and it *not* replacing the tree the
way restoring the same kind of zip does.) Both snapshot the current tree first, so the list is
mostly a history of "the state right before the last few destructive writes"; the Backup button
adds one on request. Only the newest `backups` are kept, whichever way they were made.

Settings ([plugin.system] in eznix.toml):
  backups   how many backups to keep (default 5; 0: none)
  dotfiles  include dot-files and dot-folders in an export (default false)
  exclude   file names to leave out of an export, anywhere in the tree
"""
import datetime
import io
import os
import shutil
import zipfile

PREFIX = 'system-'


def setup(api):
    flake = os.path.realpath(api.flake)
    backup_dir = os.path.join(api.state_dir, 'system-backups')
    keep = int(api.config.get('backups', 5))
    skip_dotfiles = not api.config.get('dotfiles', False)
    exclude = {str(n) for n in api.config.get('exclude', []) if str(n).strip()}
    api.page = {'backups': keep > 0}

    def tree_files():
        """(absolute path, path in the zip) for every file an export holds. Dot-files and
        dot-folders are left out by default -- .git, .direnv, key material is conventionally
        dot-prefixed, and this is a deliberately blunt way to keep secrets out of a
        downloadable zip. Symlinks are always skipped: `nix build`'s "result" links point into
        /nix/store, and without them this is a plain walk with no cycles."""
        for dirpath, dirnames, filenames in os.walk(flake):
            dirnames[:] = [d for d in dirnames
                           if not (skip_dotfiles and d.startswith('.'))
                           and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if (skip_dotfiles and fn.startswith('.')) or fn in exclude or os.path.islink(full):
                    continue
                yield full, os.path.relpath(full, flake).replace(os.sep, '/')

    def backup():
        """Zip the current tree into the backup folder and prune to the newest `keep`. Returns
        (its name, how many files it holds), or None when backups are switched off."""
        if keep <= 0:
            return None
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        dest, i = os.path.join(backup_dir, f'{PREFIX}{stamp}.zip'), 1
        while os.path.exists(dest):
            dest, i = os.path.join(backup_dir, f'{PREFIX}{stamp}-{i}.zip'), i + 1
        count = 0
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            for full, arcname in tree_files():
                zf.write(full, arcname)
                count += 1
        for old in [b['name'] for b in listing()][keep:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass
        return os.path.basename(dest), count

    def listing():
        items = []
        if os.path.isdir(backup_dir):
            for name in os.listdir(backup_dir):
                if name.startswith(PREFIX) and name.endswith('.zip'):
                    st = os.stat(os.path.join(backup_dir, name))
                    items.append({'name': name, 'mtime': st.st_mtime, 'size': st.st_size})
        return sorted(items, key=lambda b: b['mtime'], reverse=True)

    def same(target, zf, info):
        try:
            if os.path.getsize(target) != info.file_size:
                return False
            with zf.open(info) as a, open(target, 'rb') as b:
                return a.read() == b.read()
        except OSError:
            return False

    def writable(target):
        """Could eznix write this file: over it when it exists, else into the nearest folder
        that does."""
        if os.path.lexists(target):
            return os.access(target, os.W_OK)
        folder = os.path.dirname(target)
        while not os.path.exists(folder):
            folder = os.path.dirname(folder)
        return os.access(folder, os.W_OK | os.X_OK)

    def prepare(zf):
        """What making the tree match the zip takes, decided before anything is touched (the
        snapshot included): {'write': [(target, entry)], 'remove': [(path, name)], 'skipped',
        'unchanged'}.

        An entry with an empty, '.', '..' or dot-prefixed path segment is skipped and reported:
        that mirrors the export's own dot-file rule (a zip built elsewhere can't write into .git
        or .ssh) and is also what stops a path-traversal entry.

        A file that is already what the zip holds is left alone, and all the rest has to be
        something eznix may change, or nothing is. That is for NixOS, where the service owns
        its folder of *.json files and the rest of the flake is root's: writing what it could
        and failing on flake.nix left the tree half one thing and half the other. This way an
        import that only differs inside that folder goes through there, and any other is
        refused whole, with the files named."""
        write, skipped, unchanged, names = [], [], 0, set()
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace('\\', '/')
            if any(p in ('', '.', '..') or p.startswith('.') for p in rel.split('/')):
                skipped.append(info.filename)
                continue
            target = os.path.realpath(os.path.join(flake, rel))
            if os.path.commonpath([flake, target]) != flake:
                # Not expected after the check above; abort before writing anything.
                raise api.Error(400, 'invalid entry path: ' + info.filename)
            names.add(os.path.relpath(target, flake).replace(os.sep, '/'))
            if same(target, zf, info):
                unchanged += 1
            else:
                write.append((target, info))
        remove = [(full, arcname) for full, arcname in tree_files() if arcname not in names]
        denied = ([os.path.relpath(t, flake) for t, _ in write if not writable(t)]
                  + [name for full, name in remove if not os.access(os.path.dirname(full), os.W_OK | os.X_OK)])
        if denied:
            raise api.Error(403, f'eznix may not change {len(denied)} of the files this would change '
                                 f'({", ".join(denied[:3])}{", ..." if len(denied) > 3 else ""}); nothing was changed')
        return {'write': write, 'remove': remove, 'skipped': skipped, 'unchanged': unchanged}

    def apply(zf, plan):
        """Carry out what prepare() decided."""
        written = []
        for target, info in plan['write']:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            written.append(os.path.relpath(target, flake).replace(os.sep, '/'))
        removed = []
        for full, arcname in plan['remove']:
            try:
                os.remove(full)
                removed.append(arcname)
            except OSError:
                pass
        return {'ok': True, 'written': written, 'skipped': plan['skipped'], 'removed': removed,
                'unchanged': plan['unchanged']}

    def export(req):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for full, arcname in tree_files():
                zf.write(full, arcname)
        return api.Download(buf.getvalue(), 'application/zip', f'{api.hostname}-system.zip')

    def import_(req):
        try:
            zf = zipfile.ZipFile(io.BytesIO(req.body))
        except zipfile.BadZipFile:
            raise api.Error(400, 'not a valid zip file')
        with zf:
            plan = prepare(zf)
            backup()
            return apply(zf, plan)

    def restore(req):
        name = req.query.get('name', '')
        path = os.path.join(backup_dir, name)
        if not name or '/' in name or '\\' in name or name in ('.', '..') or not os.path.isfile(path):
            raise api.Error(400, 'no such backup')
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise api.Error(500, 'backup is not a valid zip file')
        # The backup being restored may itself be pruned by the snapshot taken here, so it is
        # open before that happens.
        with zf:
            plan = prepare(zf)
            backup()
            return apply(zf, plan)

    def backup_now(req):
        made = backup()
        if not made:
            raise api.Error(400, 'backups are switched off ([plugin.system] backups = 0)')
        return {'ok': True, 'name': made[0], 'files': made[1]}

    api.get('export', export)
    api.get('backups', lambda req: {'backups': listing()})
    api.post('backup', backup_now)
    api.post('import', import_)
    api.post('restore', restore)
