"""Server half of the system plugin: the whole flake as a zip, out and back in.

  GET  export           download the flake as a zip
  POST import           replace the flake's files with an uploaded zip's
  GET  backups          the backups, newest first
  POST backup           make one now
  POST delete?name=N    remove one
  POST restore?name=N   replace the flake's files with a backup's
  GET  sources[?refresh=1]  the systems the `sources` setting offers, as a tree
  POST import-source    {"url", "path"}: import one of them, as an import of a zip does

Import and restore are the same operation on a zip from two places. Both write straight to
disk, and both delete every in-scope file the zip doesn't mention, so the tree ends up matching
the zip exactly instead of merging into what was there. (Import used to be a merge; the
surprising case turned out to be importing your own export and it *not* replacing the tree the
way restoring the same kind of zip does.) Both snapshot the current tree first, so the list is
mostly a history of "the state right before the last few destructive writes"; the Backup button
adds one on request. Only the newest `backups` are kept, whichever way they were made.

Settings ([plugin.system] in eznix.toml):
  backups   how many backups to keep (default 5; 0: none)
  exclude   what to leave out of an export, each entry read like a line of a .gitignore, as
            eznix's own `exclude` is: a name anywhere in the tree (a folder with everything
            under it), "/name" from the top of the flake, * ? [a-z] **, "!entry"
            (api.ignore). Default [".*"]: dot-files and dot-folders. A list of your own
            replaces that, so it has to say ".*" itself to keep them out.
            Until 2026-10-12 it was two settings, a switch `dotfiles` and a list of exact
            file names; the user wanted the one list, with the dot-files as its default.
  keep      what an import leaves as it is on this machine, read the same way: a file that
            is there is neither replaced by the zip's nor removed for not being in it; one
            that is not there is taken from the zip. Default ["hardware-configuration.nix"]:
            that file describes the machine, and a system brought from another one came
            with the other machine's (the user, 2026-10-13, about to import a template
            made on a VM). eznix cannot make a new one, which takes root. A restore keeps
            nothing back: a backup is this machine's own.
  sources   where systems can be imported from (2026-10-19, the user's idea), each a location
            or {name, url}. A location is an https address or a path on this machine (an
            installer's own templates), and what is there is a zip or an index, told apart by
            their first bytes. In a zip every folder with a flake.nix is a system, so one
            zip can hold many and a repository downloaded from GitHub works as it is (its
            one folder around everything is left out of the names). An index is JSON:
            {"items": [...]} or the list alone, an item {name, url, path, description} or
            {name, items} for a folder of its own; a url in it is relative to the index, and
            one in an index on the web has to be https too. Only what the setting leads to
            can be imported: the page names a system by its zip's location and folder, and
            that location must have been reached from the setting. Plain http is refused,
            since what is imported is built as root at the next rebuild. A download is kept
            in the state folder for SOURCE_TTL and used again, and used when fetching it
            again fails.
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

PREFIX = 'system-'

# What a zip may hold to be taken as a system (prepare()): a flake is text, a few thousand
# files at the most.
MAX_ENTRIES  = 100_000
MAX_UNPACKED = 2 << 30
MAX_FILE     = 1 << 30

# What a source may be: how much is downloaded, how long a download is used again, how long
# one may take, and how deep indexes may lead to more indexes.
MAX_DOWNLOAD = 256 << 20
SOURCE_TTL   = 600
FETCH_TIMEOUT = 30
MAX_DEPTH    = 4


def setup(api):
    flake = os.path.realpath(api.flake)
    backup_dir = os.path.join(api.state_dir, 'system-backups')
    keep = int(api.config.get('backups', 5))
    excluded = api.ignore(api.config.get('exclude', ['.*']))
    stays = api.ignore(api.config.get('keep', ['hardware-configuration.nix']))
    sources = [e if isinstance(e, dict) else {'url': e} for e in api.config.get('sources', [])]
    source_dir = os.path.join(api.state_dir, 'system-sources')
    reached = set()     # every zip's location a listing of `sources` has led to
    api.page = {'backups': keep > 0, 'sources': bool(sources)}

    def tree_files():
        """(absolute path, path in the zip) for every file an export holds: all but what
        `exclude` leaves out, which is dot-files and dot-folders unless it says otherwise --
        .git, .direnv, key material is conventionally dot-prefixed, and this is a
        deliberately blunt way to keep secrets out of a downloadable zip. Symlinks are always skipped: `nix build`'s "result" links point into
        /nix/store, and without them this is a plain walk with no cycles."""
        for dirpath, dirnames, filenames in os.walk(flake):
            rel = lambda name: os.path.relpath(os.path.join(dirpath, name), flake).replace(os.sep, '/')
            dirnames[:] = [d for d in dirnames
                           if not excluded(rel(d)) and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if excluded(rel(fn)) or os.path.islink(full):
                    continue
                yield full, rel(fn)

    def backup():
        """Zip the current tree into the backup folder and prune to the newest `keep`. Returns
        (its name, how many files it holds), or None when backups are switched off."""
        if keep <= 0:
            return None
        # Written by eznix alone, whatever the umask: under the NixOS service's UMask 0002 the
        # folder was 0775 and the zips 0664, so any user in `users` could put a "backup" of
        # their own there for someone else to restore (2026-10-18).
        os.makedirs(backup_dir, mode=0o755, exist_ok=True)
        try:
            os.chmod(backup_dir, 0o755)
        except OSError:
            pass
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        dest, i = os.path.join(backup_dir, f'{PREFIX}{stamp}.zip'), 1
        while os.path.exists(dest):
            dest, i = os.path.join(backup_dir, f'{PREFIX}{stamp}-{i}.zip'), i + 1
        count = 0
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            for full, arcname in tree_files():
                zf.write(full, arcname)
                count += 1
        os.chmod(dest, 0o644)
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

    def prepare(zf, keeping=False):
        """What making the tree match the zip takes, decided before anything is touched (the
        snapshot included): {'write': [(target, entry)], 'remove': [(path, name)], 'skipped',
        'unchanged', 'kept'}. `keeping`, for an import: what the `keep` setting names stays
        as it is on this machine ('kept').

        An entry with an empty, '.', '..' or dot-prefixed path segment is skipped and reported:
        that mirrors the export's own dot-file rule (a zip built elsewhere can't write into .git
        or .ssh) and is also what stops a path-traversal entry.

        A file that is already what the zip holds is left alone, and all the rest has to be
        something eznix may change, or nothing is. That is for NixOS, where the service owns
        its folder of *.json files and the rest of the flake is root's: writing what it could
        and failing on flake.nix left the tree half one thing and half the other. This way an
        import that only differs inside that folder goes through there, and any other is
        refused whole, with the files named."""
        # A system is a flake, so its zip has flake.nix at the top: what an export holds, and a
        # backup. Any other zip (one of a folder of JSON files, somebody's photographs, a
        # repository downloaded with a folder around it) is refused here, before the snapshot
        # and before anything is touched. It used to be taken for a system all the same, and
        # since the tree is made to match the zip, every file of the flake that was not in it
        # was removed. The user's question, 2026-10-13: "is there some way we can validate
        # the zip ... to make sure its actually a system?"
        # And not a zip made to fill the disk or the memory: how many entries, how much they
        # hold when unpacked, and how much one does. The sizes are the zip's own claims, and
        # reading stops at them (ZipExtFile reads no more than file_size), so they bind what
        # is written. 2026-10-16.
        infos = zf.infolist()
        if (len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED
                or any(i.file_size > MAX_FILE for i in infos)):
            raise api.Error(413, 'that zip is too big to be a system (more than '
                                 f'{MAX_ENTRIES} files, {MAX_UNPACKED >> 30} GiB unpacked, or a file over '
                                 f'{MAX_FILE >> 30} GiB); nothing was changed')
        tops = [i.filename.replace('\\', '/') for i in zf.infolist() if not i.is_dir()]
        if 'flake.nix' not in tops:
            deeper = sorted(n for n in tops if n.endswith('/flake.nix'))
            hint = f': its flake.nix is in {os.path.dirname(deeper[0])}/, not at the top' if deeper else ': there is no flake.nix at its top'
            raise api.Error(400, 'that zip is not a system' + hint + '; nothing was changed')
        write, skipped, unchanged, names, kept = [], [], 0, set(), []
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
            name = os.path.relpath(target, flake).replace(os.sep, '/')
            names.add(name)
            if keeping and stays(name) and os.path.exists(target):
                kept.append(name)
            elif same(target, zf, info):
                unchanged += 1
            else:
                write.append((target, info))
        remove = [(full, arcname) for full, arcname in tree_files()
                  if arcname not in names and not (keeping and stays(arcname))]
        denied = ([os.path.relpath(t, flake) for t, _ in write if not writable(t)]
                  + [name for full, name in remove if not os.access(os.path.dirname(full), os.W_OK | os.X_OK)])
        if denied:
            raise api.Error(403, f'eznix may not change {len(denied)} of the files this would change '
                                 f'({", ".join(denied[:3])}{", ..." if len(denied) > 3 else ""}); nothing was changed')
        return {'write': write, 'remove': remove, 'skipped': skipped, 'unchanged': unchanged, 'kept': kept}

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
                'unchanged': plan['unchanged'], 'kept': plan['kept']}

    def is_web(loc):
        return loc.startswith('https://')

    def location(base, ref):
        """Where `ref` in an index at `base` points (`base` None: `ref` is from the setting).
        An https address, or an absolute path on this machine; from an index on the web, only
        an https address."""
        ref = str(ref).strip()
        if ref.startswith('file://'):
            ref = urllib.parse.unquote(urllib.parse.urlparse(ref).path)
        if base and is_web(base):
            loc = urllib.parse.urljoin(base, ref)
            if not is_web(loc):
                raise ValueError('an index on the web can only lead to https addresses')
            return loc
        if is_web(ref) or os.path.isabs(ref):
            return ref
        if '://' in ref:
            raise ValueError('only https addresses and paths on this machine')
        if not base:
            raise ValueError('a path has to start at /')
        return os.path.normpath(os.path.join(os.path.dirname(base), ref))

    def fetch(loc, refresh=False):
        """What is at a location: a file read, or a download kept in the state folder."""
        if not is_web(loc):
            if os.path.getsize(loc) > MAX_DOWNLOAD:
                raise ValueError(f'more than {MAX_DOWNLOAD >> 20} MiB')
            with open(loc, 'rb') as f:
                return f.read()
        kept = os.path.join(source_dir, hashlib.sha256(loc.encode()).hexdigest()[:32])
        if not refresh and os.path.isfile(kept) and time.time() - os.path.getmtime(kept) < SOURCE_TTL:
            with open(kept, 'rb') as f:
                return f.read()
        try:
            req = urllib.request.Request(loc, headers={'User-Agent': 'eznix'})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                if not is_web(r.geturl()):
                    raise ValueError('it was redirected away from https')
                data = r.read(MAX_DOWNLOAD + 1)
            if len(data) > MAX_DOWNLOAD:
                raise ValueError(f'more than {MAX_DOWNLOAD >> 20} MiB')
        except Exception:
            if os.path.isfile(kept):
                api.debug(f'source {loc}: fetching failed, using what was downloaded before')
                with open(kept, 'rb') as f:
                    return f.read()
            raise
        # Written by eznix alone, as the backups are.
        os.makedirs(source_dir, mode=0o755, exist_ok=True)
        try:
            os.chmod(source_dir, 0o755)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(dir=source_dir)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, kept)
        return data

    def systems_in(zf):
        """The folders of a zip that hold a flake.nix, and the one folder around everything
        (a repository downloaded from GitHub), or ''."""
        names = [i.filename.replace('\\', '/') for i in zf.infolist() if not i.is_dir()]
        found = sorted({os.path.dirname(n) for n in names if n == 'flake.nix' or n.endswith('/flake.nix')})
        found = [d for d in found if not d or all(p not in ('.', '..') and not p.startswith('.') for p in d.split('/'))]
        tops = {n.split('/')[0] for n in names}
        around = next(iter(tops)) if len(tops) == 1 and all('/' in n for n in names) else ''
        return found, around

    def zip_node(name, loc, data, path=None, description=None):
        """`name` empty: the folder around everything, else the file's name."""
        zf = zipfile.ZipFile(io.BytesIO(data))
        found, around = systems_in(zf)
        reached.add(loc)
        name = name or around or os.path.splitext(os.path.basename(loc.rstrip('/')))[0] or loc
        leaf = lambda label, folder: {'name': label, 'url': loc, 'path': folder,
                                      **({'description': description} if description else {})}
        if path is not None:
            path = path.strip('/')
            if path not in found:
                raise ValueError(f'there is no flake.nix in {path or "its top"}')
            return leaf(name, path)
        if not found:
            raise ValueError('it holds no flake.nix')
        if len(found) == 1:
            return leaf(name, found[0])
        # A tree by folder; a folder that is a system and holds others is both.
        root = {'name': name, 'items': []}
        if description:
            root['description'] = description
        for folder in found:
            shown = folder[len(around):].strip('/') if around else folder
            node = root
            for part in [p for p in shown.split('/') if p]:
                sub = next((n for n in node['items'] if n['name'] == part and 'items' in n), None)
                if not sub:
                    sub = {'name': part, 'items': []}
                    node['items'].append(sub)
                node = sub
            if node is root:
                root['items'].insert(0, leaf(around or name, folder))
            else:
                node['url'], node['path'] = loc, folder
        def leaves(n):
            for sub in n.get('items', []):
                leaves(sub)
            if 'items' in n and not n['items'] and n is not root:
                del n['items']
        leaves(root)
        return root

    def node(item, base, depth, refresh):
        """One entry of the setting or of an index, as the page shows it: a system {name,
        url, path}, a folder {name, items}, or {name, error}."""
        name = str(item.get('name') or '')
        try:
            if 'items' in item:
                return {'name': name or 'systems', 'items': [node(i, base, depth, refresh) for i in item['items']]}
            loc = location(base, item['url'])
            data = fetch(loc, refresh)
            if data[:2] == b'PK':
                return zip_node(name, loc, data, item.get('path'), item.get('description'))
            name = name or os.path.splitext(os.path.basename(loc.rstrip('/')))[0] or loc
            if depth >= MAX_DEPTH:
                raise ValueError('indexes lead to indexes too deep')
            index = json.loads(data.decode('utf-8'))
            items = index if isinstance(index, list) else index.get('items', [])
            if not isinstance(index, list):
                name = item.get('name') or index.get('name') or name
            return {'name': name, 'items': [node(i if isinstance(i, dict) else {'url': i}, loc, depth + 1, refresh)
                                            for i in items]}
        except Exception as e:
            api.debug(f'source {item!r}: {e}')
            why = e.reason if isinstance(e, urllib.error.URLError) else (e.strerror or e) if isinstance(e, OSError) else e
            return {'name': name or str(item.get('url', '')), 'error': str(why)}

    def list_sources(refresh=False):
        return {'sources': [node(s, None, 0, refresh) for s in sources]}

    def import_source(req):
        try:
            asked = json.loads(req.body or b'{}')
            loc, path = asked['url'], asked.get('path') or ''
        except (ValueError, KeyError, TypeError):
            raise api.Error(400, 'name a system as {"url", "path"}')
        if loc not in reached:
            list_sources()
        if loc not in reached:
            raise api.Error(400, 'that is not one of the systems in `sources`')
        try:
            data = fetch(loc)
            zf = zipfile.ZipFile(io.BytesIO(data))
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            raise api.Error(502, f'could not get {loc}: {e}')
        with zf:
            if path not in systems_in(zf)[0]:
                raise api.Error(400, f'there is no system in {path or "the top"} of {loc}')
            sub = zf if not path else folder_zip(zf, path)
            plan = prepare(sub, keeping=True)
            backup()
            return apply(sub, plan)

    def folder_zip(zf, path):
        """One folder of a zip as a zip of its own, its files at the top, for prepare(). The
        limits are prepare()'s, checked here before anything is copied."""
        prefix = path + '/'
        infos = [i for i in zf.infolist() if not i.is_dir() and i.filename.replace('\\', '/').startswith(prefix)]
        if (len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED
                or any(i.file_size > MAX_FILE for i in infos)):
            raise api.Error(413, 'that system is too big; nothing was changed')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as out:
            for i in infos:
                out.writestr(i.filename.replace('\\', '/')[len(prefix):], zf.read(i))
        return zipfile.ZipFile(buf)

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
            plan = prepare(zf, keeping=True)
            backup()
            return apply(zf, plan)

    def backup_path(req):
        """The backup a request names, which has to be one of the list's own."""
        name = req.query.get('name', '')
        path = os.path.join(backup_dir, name)
        if (not name or '/' in name or '\\' in name or not name.startswith(PREFIX)
                or not name.endswith('.zip') or not os.path.isfile(path)):
            raise api.Error(400, 'no such backup')
        return path

    def delete(req):
        try:
            os.remove(backup_path(req))
        except OSError as e:
            raise api.Error(500, f'could not remove it: {e.strerror}')
        return {'ok': True}

    def restore(req):
        path = backup_path(req)
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
    api.post('delete', delete)
    api.post('import', import_)
    api.post('restore', restore)
    api.get('sources', lambda req: list_sources(req.query.get('refresh') == '1'))
    api.post('import-source', import_source)
