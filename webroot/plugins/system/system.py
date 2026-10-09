"""Server half of the system plugin: the whole flake as a zip, out and back in.

  GET  export           download the flake as a zip
  POST import           replace the flake's files with an uploaded zip's
  GET  backups          the automatic backups, newest first
  POST restore?name=N   replace the flake's files with a backup's

Import and restore are the same operation on a zip from two places. Both write straight to
disk, and both delete every in-scope file the zip doesn't mention, so the tree ends up matching
the zip exactly instead of merging into what was there. (Import used to be a merge; the
surprising case turned out to be importing your own export and it *not* replacing the tree the
way restoring the same kind of zip does.) Both snapshot the current tree first -- that is the
only thing that ever makes a backup, so the list is a history of "the state right before the
last few destructive writes".

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
        """Zip the current tree into the backup folder and prune to the newest `keep`."""
        if keep <= 0:
            return
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        dest, i = os.path.join(backup_dir, f'{PREFIX}{stamp}.zip'), 1
        while os.path.exists(dest):
            dest, i = os.path.join(backup_dir, f'{PREFIX}{stamp}-{i}.zip'), i + 1
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            for full, arcname in tree_files():
                zf.write(full, arcname)
        for old in [b['name'] for b in listing()][keep:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass

    def listing():
        items = []
        if os.path.isdir(backup_dir):
            for name in os.listdir(backup_dir):
                if name.startswith(PREFIX) and name.endswith('.zip'):
                    st = os.stat(os.path.join(backup_dir, name))
                    items.append({'name': name, 'mtime': st.st_mtime, 'size': st.st_size})
        return sorted(items, key=lambda b: b['mtime'], reverse=True)

    def apply(zf):
        """Make the tree match the zip. Every entry is checked before any is written. An entry
        with an empty, '.', '..' or dot-prefixed path segment is skipped and reported: that
        mirrors the export's own dot-file rule (a zip built elsewhere can't write into .git or
        .ssh) and is also what stops a path-traversal entry."""
        plan, skipped = [], []
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
            plan.append((target, info))
        written = []
        for target, info in plan:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            written.append(os.path.relpath(target, flake).replace(os.sep, '/'))
        removed, kept = [], set(written)
        for full, arcname in list(tree_files()):
            if arcname not in kept:
                try:
                    os.remove(full)
                    removed.append(arcname)
                except OSError:
                    pass
        return {'ok': True, 'written': written, 'skipped': skipped, 'removed': removed}

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
        backup()
        with zf:
            return apply(zf)

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
            backup()
            return apply(zf)

    api.get('export', export)
    api.get('backups', lambda req: {'backups': listing()})
    api.post('import', import_)
    api.post('restore', restore)
