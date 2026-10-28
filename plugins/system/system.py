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
  protect   what belongs to this machine and is never touched: not exported, not backed up,
            never written or removed by an import or a restore (2026-10-26, the user's).
            Default [".git"], the repository; read like `exclude`. A .gitignore is the flake's
            and travels. It is all that an import or a restore leaves alone: an import changes
            the whole system, and leaves none of the old files (the user's, the same day: "i
            dont want there to be any old files left"); the backup taken first holds them, and
            what the new system needs and does not bring, its `generate` makes. For some hours
            that day an import left alone the zip's own `exclude` (this machine's when it had
            none), and before that this machine's.
  exclude   since 2026-10-26: what an export leaves out, nothing more (backups hold it, an
            import and a restore remove it like anything else). Before that day:
            the files and folders eznix never touches, in an export, a backup, an import and a
            restore alike (the user's rule, 2026-10-22: one list, "everything but the excluded
            files" out, and an import "has to look exactly like the zip-file structure + the
            excluded files if they existed"). Each entry is read like a line of a .gitignore,
            as eznix's own `exclude` is: a name anywhere in the tree (a folder with everything
            under it), "/name" from the top of the flake, * ? [a-z] **, "!entry"
            (api.ignore). Default ["hardware-configuration.nix"] (".git" too until `protect`): the
            file that describes this machine, which a system brought from another one
            came with the other machine's (it was a setting of its own, `keep`, until
            then). A list of your own replaces that. An import writes the zip's files and
            folders (an empty folder too) and removes every file and folder it doesn't hold,
            all but what `exclude` names; a path of the zip that `exclude` names is skipped.
            A restore writes all that its backup holds, since a backup is eznix's own and may
            be of another `exclude`, and removes by the one there is now.
            Until 2026-10-12 it was two settings, a switch `dotfiles` and a list of exact
            file names; the user wanted the one list.
  generate  [{file, command}]: files to make when an import leaves them missing, each with the
            command that makes it (2026-10-22, the user's idea; the machine's hardware file
            was the first, and it was `hardware` and one file until the user said any file
            could be one). No defaults, since it has to fit every platform and a template
            sets it: nothing set, nothing checked. A dry run (POST import and import-source
            with dry) tells the page what an import would do, a flake.nix missing from the zip
            and files missing afterwards included, and the page asks before it goes on; after
            the import it runs the commands in the terminal, one after the other (sudo asks
            there). The list can also be in the zip, in its configuration folder at
            services.eznix.plugins.system.generate (a template says how its machine gets its
            files), from any zip, uploaded or from a source; the running configuration's
            setting is used only when the zip has none. The question before the import shows
            every command that will run, which is where the user says yes to them (2026-10-26:
            an uploaded zip's list was not taken, a rule the user had not asked for, and a
            system uploaded onto a machine then did not get the files it needs).
  open      [path]: files to open after an import, relative to the flake (2026-10-25, the
            user's idea: a template's README.md). Read from the zip's configuration folder, at
            services.eznix.plugins.system.open, from any zip, since it runs nothing: the page
            opens each that is there afterwards with whatever it has for its kind (the 'open'
            event: Documents for .md, a menu of the files plugin for its endings, a tab for
            one of the editor's own JSON files). Set in the running configuration it does
            nothing.
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
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

PREFIX = 'system-'
DEFAULT_EXCLUDE = ['hardware-configuration.nix']   # what `exclude` is unless it is set
DEFAULT_PROTECT = ['.git']                         # what `protect` is unless it is set

# What a zip may hold to be taken as a system (prepare()): a flake is text, a few thousand
# files at the most.
MAX_ENTRIES  = 100_000
MAX_UNPACKED = 2 << 30
MAX_FILE     = 1 << 30

# What a source may be: how much is downloaded, how long a download is used again, how long
# one may take, and how deep indexes may lead to more indexes.
MAX_DOWNLOAD  = 256 << 20
SOURCE_TTL    = 600
FETCH_TIMEOUT = 30
MAX_INFO      = 500
MAX_DEPTH     = 4


def setup(api):
    flake = os.path.realpath(api.flake)
    backup_dir = os.path.join(api.state_dir, 'system-backups')
    keep = int(api.config.get('backups', 5))
    protected = api.ignore(api.config.get('protect', DEFAULT_PROTECT))
    excluded = api.ignore(api.config.get('exclude', DEFAULT_EXCLUDE))
    # What this machine leaves out of an export: both lists.
    here = lambda rel: protected(rel) or excluded(rel)
    sources = [e if isinstance(e, dict) else {'url': e} for e in api.config.get('sources', [])]
    source_dir = os.path.join(api.state_dir, 'system-sources')
    reached = set()     # every zip's (or folder's) location a listing of `sources` has led to
    addable = set()     # the locations a source with `add_only` has led to
    api.page = {'backups': keep > 0, 'sources': bool(sources)}

    def tree_files(skip):
        """(absolute path, path in the zip) for every file but what `skip` (a path's test) leaves
        out: `here` for an export, `protected` for a backup and for what an import removes. Symlinks are always skipped: `nix build`'s "result" links point into
        /nix/store, and without them this is a plain walk with no cycles."""
        for dirpath, dirnames, filenames in os.walk(flake):
            rel = lambda name: os.path.relpath(os.path.join(dirpath, name), flake).replace(os.sep, '/')
            dirnames[:] = [d for d in dirnames
                           if not skip(rel(d)) and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if skip(rel(fn)) or os.path.islink(full):
                    continue
                yield full, rel(fn)

    def tree_dirs(skip):
        """The same for the folders, so that an empty one is in a zip as well."""
        for dirpath, dirnames, filenames in os.walk(flake):
            rel = lambda name: os.path.relpath(os.path.join(dirpath, name), flake).replace(os.sep, '/')
            dirnames[:] = [d for d in dirnames
                           if not skip(rel(d)) and not os.path.islink(os.path.join(dirpath, d))]
            for d in dirnames:
                yield os.path.join(dirpath, d), rel(d)

    def left_alone(skip):
        """The paths on disk that `skip` names, a folder once (ending in '/') and not what is in
        it, for the question before an import. Links are left out, as everywhere."""
        out = []
        for dirpath, dirnames, filenames in os.walk(flake):
            rel = lambda name: os.path.relpath(os.path.join(dirpath, name), flake).replace(os.sep, '/')
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
            out += [rel(d) + '/' for d in dirnames if skip(rel(d))]
            dirnames[:] = [d for d in dirnames if not skip(rel(d))]
            out += [rel(fn) for fn in filenames if skip(rel(fn)) and not os.path.islink(os.path.join(dirpath, fn))]
        return sorted(out)

    def write_tree(zf, skip):
        """The tree into a zip: its folders (an empty one has to be in it) and its files."""
        for full, arcname in tree_dirs(skip):
            zf.write(full, arcname)
        count = 0
        for full, arcname in tree_files(skip):
            zf.write(full, arcname)
            count += 1
        return count

    def backup():
        """Zip the current tree into the backup folder and prune to the newest `keep`. Returns
        (its name, how many files it holds), or None when backups are switched off. All of it
        but what `protect` names, `exclude`'s paths included: an import goes by the zip's
        `exclude`, and can remove what this machine's left out (2026-10-26)."""
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
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            count = write_tree(zf, protected)
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
        # A file in the way of a folder is removed first (apply()), so the folder above it counts.
        while not os.path.isdir(folder):
            folder = os.path.dirname(folder)
        return os.access(folder, os.W_OK | os.X_OK)

    def prepare(zf, removing=True):
        """What making the tree look exactly like the zip takes, decided before anything is
        touched (the snapshot included): {'write': [(target, entry)], 'make': [folder],
        'remove': [(path, name)], 'remove_dirs': [(path, name)], 'skipped', 'unchanged'}.

        The tree ends up as the zip has it, files and folders, and what `protect` names is left
        as it is: a file or folder of the zip that it names is not written ('skipped'), and one
        on disk that it names is not removed. Nothing else is left: `exclude` is the export's.
        `removing` false: nothing is removed, the zip is only added over what is there (a
        source with `add_only`). A zip without a flake.nix is not refused: check() tells the
        page, which asks before it goes on (the user, 2026-10-22: it should warn, "people can
        import whatever"); an empty backup is an empty zip.

        An entry with an empty, '.' or '..' path segment is skipped and reported, which is
        also what stops a path-traversal entry.

        A file that is already what the zip holds is left alone, and all the rest has to be
        something eznix may change, or nothing is. That is for NixOS, where the service owns
        its folder of *.json files and the rest of the flake is root's: writing what it could
        and failing on flake.nix left the tree half one thing and half the other. This way an
        import that only differs inside that folder goes through there, and any other is
        refused whole, with the files named."""
        # Not a zip made to fill the disk or the memory: how many entries, how much they
        # hold when unpacked, and how much one does. The sizes are the zip's own claims, and
        # reading stops at them (ZipExtFile reads no more than file_size), so they bind what
        # is written. 2026-10-16.
        infos = zf.infolist()
        if (len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED
                or any(i.file_size > MAX_FILE for i in infos)):
            raise api.Error(413, 'that zip is too big to be a system (more than '
                                 f'{MAX_ENTRIES} files, {MAX_UNPACKED >> 30} GiB unpacked, or a file over '
                                 f'{MAX_FILE >> 30} GiB); nothing was changed')
        write, make, skipped, unchanged, names, folders = [], [], [], 0, set(), set()
        for info in zf.infolist():
            rel = info.filename.replace('\\', '/').rstrip('/')
            if any(p in ('', '.', '..') for p in rel.split('/')):
                skipped.append(info.filename)
                continue
            target = os.path.realpath(os.path.join(flake, rel))
            if os.path.commonpath([flake, target]) != flake:
                # Not expected after the check above; abort before writing anything.
                raise api.Error(400, 'invalid entry path: ' + info.filename)
            name = os.path.relpath(target, flake).replace(os.sep, '/')
            if protected(name):
                skipped.append(info.filename)
                continue
            # Every folder above what the zip holds is one it holds, and a folder entry is one.
            parts = name.split('/')
            folders.update('/'.join(parts[:n]) for n in range(1, len(parts) + 1 if info.is_dir() else len(parts)))
            if info.is_dir():
                if not os.path.isdir(target):
                    make.append(target)
                continue
            names.add(name)
            if same(target, zf, info):
                unchanged += 1
            else:
                write.append((target, info))
        remove = [(full, arcname) for full, arcname in tree_files(protected) if removing and arcname not in names]
        remove_dirs = sorted(((full, arcname) for full, arcname in tree_dirs(protected) if removing and arcname not in folders),
                             key=lambda f: -f[1].count('/'))
        denied = ([os.path.relpath(t, flake) for t, _ in write if not writable(t)]
                  + [os.path.relpath(t, flake) for t in make if not writable(t)]
                  + [name for full, name in remove + remove_dirs
                     if not os.access(os.path.dirname(full), os.W_OK | os.X_OK)])
        if denied:
            raise api.Error(403, f'eznix may not change {len(denied)} of the files this would change '
                                 f'({", ".join(denied[:3])}{", ..." if len(denied) > 3 else ""}); nothing was changed')
        return {'write': write, 'make': make, 'remove': remove, 'remove_dirs': remove_dirs,
                'skipped': skipped, 'unchanged': unchanged, 'names': names}

    def apply(zf, plan):
        """Carry out what prepare() decided: what the zip does not hold is removed first, files,
        then folders (deepest first; one that still holds something, a path `exclude` leaves
        alone, stays), and then its folders are made and its files written as they are. In that
        order a file where the zip has a folder, or a folder where it has a file, is out of the
        way before anything is written."""
        removed = []
        for full, arcname in plan['remove']:
            try:
                os.remove(full)
                removed.append(arcname)
            except OSError:
                pass
        removed_folders = []
        for full, arcname in plan['remove_dirs']:
            try:
                os.rmdir(full)
                removed_folders.append(arcname)
            except OSError:
                pass
        for folder in plan['make']:
            os.makedirs(folder, exist_ok=True)
        written = []
        for target, info in plan['write']:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            written.append(os.path.relpath(target, flake).replace(os.sep, '/'))
        if written or removed or removed_folders:
            forget_suggestions()
        return {'ok': True, 'written': written, 'skipped': plan['skipped'], 'removed': removed,
                'removed_folders': removed_folders, 'unchanged': plan['unchanged']}

    def forget_suggestions():
        """The suggestions are of the system that was there: an import or a restore that changed
        anything removes them, and the page then offers to generate them for this one (its
        mark on the Autocomplete button, from the ping). Until 2026-10-25 an import generated them by itself
        (`autocomplete`), and with that off, or the run failing, the old system's stayed in the
        editor without a word; the user chose a mark and a click."""
        d = os.path.realpath(api.autocomplete_dir)
        # Every .json file in it goes, so never in the flake (the configuration is .json files)
        # or in the state folder itself (sessions.json), whatever `autocomplete_dir` is set to.
        def within(path, top):
            if not top:
                return False
            top = os.path.realpath(top)
            return os.path.commonpath([top, path]) == top
        if within(d, api.flake) or within(d, api.config_dir) or (api.state_dir and d == os.path.realpath(api.state_dir)):
            api.debug(f'suggestions not removed: {d} is in the flake or is the state folder')
            return
        try:
            names = os.listdir(d)
        except OSError:
            return
        for name in names:
            if name.endswith('.json'):
                try:
                    os.remove(os.path.join(d, name))
                except OSError:
                    pass

    def entries_of(value):
        """The usable entries of a `generate` list: {file, command}, both set. Anything else in
        it is left out."""
        out = []
        for e in value if isinstance(value, list) else []:
            if isinstance(e, dict) and '_value' in e and '_disabled' in e:
                e = None if e['_disabled'] else e['_value']
            if isinstance(e, dict) and all(isinstance(e.get(k), str) and e[k].strip() for k in ('file', 'command')):
                out.append({'file': e['file'].strip(), 'command': e['command'].strip()})
        return out

    def setting_in(zf, key):
        """The value of services.eznix.plugins.system.KEY in the JSON files of the zip's
        configuration folder, the first file that has one; None when none has. A disabled
        setting does not count."""
        rel = os.path.relpath(os.path.realpath(api.config_dir or os.path.join(flake, 'eznix')), flake).replace(os.sep, '/')
        if rel.startswith('..'):
            return None
        def step(node, key):
            if isinstance(node, dict) and '_value' in node and '_disabled' in node:
                node = None if node['_disabled'] else node['_value']
            return node.get(key) if isinstance(node, dict) else None
        for info in zf.infolist():
            name = info.filename.replace('\\', '/')
            if info.is_dir() or not name.startswith(rel + '/') or not name.endswith('.json') or info.file_size > (1 << 20):
                continue
            try:
                node = json.loads(zf.read(info))
            except ValueError:
                continue
            for k in ('services', 'eznix', 'plugins', 'system', key):
                node = step(node, k)
            if isinstance(node, dict) and '_value' in node and '_disabled' in node:
                node = None if node['_disabled'] else node['_value']
            if node is not None:
                return node
        return None

    def generate_in(zf):
        """What the zip says about files to make when an import leaves them missing: `generate`
        in its configuration, a list of {file, command}."""
        return entries_of(setting_in(zf, 'generate'))

    def open_in(zf):
        """The files the zip says to open once it is imported (`open` in its configuration, a
        list of paths in the flake: a template's README, say; 2026-10-25, the user's idea).
        Taken from any zip, uploaded or not: opening runs nothing the zip chose, a file being
        shown by whatever the running page has for its kind. Anything that is no plain
        relative path is left out."""
        value = setting_in(zf, 'open')
        out = []
        for e in value if isinstance(value, list) else []:
            if isinstance(e, dict) and '_value' in e and '_disabled' in e:
                e = None if e['_disabled'] else e['_value']
            if not isinstance(e, str):
                continue
            path = e.strip().replace('\\', '/')
            if path and not path.startswith('/') and not any(p in ('', '.', '..') for p in path.split('/')) and path not in out:
                out.append(path)
        return out

    def to_open(paths):
        """The files of `open` that are there after the import, each {path} relative to the
        flake, and `tab` when it is one of the editor's own (a .json in the configuration
        folder), for the page to switch to: the page does not know where that folder is."""
        base = os.path.realpath(flake)
        conf = os.path.realpath(api.config_dir or os.path.join(flake, 'eznix'))
        out = []
        for path in paths:
            full = os.path.join(flake, path)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            real = os.path.realpath(full)
            if os.path.commonpath([base, real]) != base:
                continue
            item = {'path': path}
            if path.endswith('.json') and os.path.commonpath([conf, real]) == conf:
                item['tab'] = os.path.relpath(real, conf).replace(os.sep, '/')
            out.append(item)
        return out

    def generate_for(zf):
        """The files to make when missing, each with the command that makes it: the zip's own
        list (the system knows what it needs), else the running configuration's. No defaults
        (the user, 2026-10-22: a template sets it, and it has to fit every platform): nothing
        set is nothing checked. Nothing runs unasked: the page shows each command in the
        question before the import."""
        return generate_in(zf) or entries_of(api.config.get('generate'))

    def check(zf, plan):
        """What an import would do, for the page to ask with: nothing is written. A zip without
        a flake.nix at its top, and files that will be missing afterwards."""
        names = [i.filename.replace('\\', '/') for i in zf.infolist() if not i.is_dir()]
        entries = generate_for(zf)
        removed = [n for _, n in plan['remove']]
        def present(file):
            return file in plan['names'] or (os.path.lexists(os.path.join(flake, file)) and file not in removed)
        gone = [n for _, n in plan['remove']]
        gone += [n + '/' for _, n in plan['remove_dirs'] if not any(g.startswith(n + '/') for g in gone)]
        return {'dry': True, 'flake_nix': 'flake.nix' in names,
                'kept': left_alone(protected), 'removed': sorted(gone),
                'generate': [{**e, 'missing': not present(e['file'])} for e in entries],
                'write': len(plan['write']), 'remove': len(plan['remove']), 'skipped': plan['skipped']}

    def run_import(zf, removing=True, dry=False):
        """An import, or with `dry` what it would do. After one, what has to be run to make the
        files that are missing, when something says how."""
        plan = prepare(zf, removing=removing)
        if dry:
            return check(zf, plan)
        entries = generate_for(zf)
        backup()
        result = apply(zf, plan)
        missing = [e for e in entries if not os.path.lexists(os.path.join(flake, e['file']))]
        if missing:
            result['generate'] = missing
        opened = to_open(open_in(zf))
        if opened:
            result['open'] = opened
        return result

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

    def kept_for(loc):
        return os.path.join(source_dir, hashlib.sha256(loc.encode()).hexdigest()[:32])

    def fetch(loc, refresh=False):
        """What is at a location: a file read, or a download kept in the state folder."""
        if not is_web(loc):
            if os.path.getsize(loc) > MAX_DOWNLOAD:
                raise ValueError(f'more than {MAX_DOWNLOAD >> 20} MiB')
            with open(loc, 'rb') as f:
                return f.read()
        kept = kept_for(loc)
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
        return tree_node(name, loc, found, around, path, description)

    def systems_in_dir(base):
        """The folders under a folder on this machine that hold a flake.nix ('' for the folder
        itself): dot-folders and links are left out, and nothing deeper than MAX_DEPTH."""
        found = []
        for dirpath, dirnames, filenames in os.walk(base):
            rel = os.path.relpath(dirpath, base).replace(os.sep, '/')
            rel = '' if rel == '.' else rel
            dirnames[:] = sorted(d for d in dirnames if not d.startswith('.')
                                 and not os.path.islink(os.path.join(dirpath, d)) and rel.count('/') < MAX_DEPTH)
            if 'flake.nix' in filenames:
                found.append(rel)
        return sorted(found)

    def dir_node(name, loc, description=None):
        reached.add(loc)
        return tree_node(name or os.path.basename(loc.rstrip('/')) or loc, loc, systems_in_dir(loc), '', None, description)

    def tree_node(name, loc, found, around, path, description):
        """The systems `found` (folders of a zip or of a folder) at `loc`, as a system or a tree."""
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

    GITHUB_TREE = re.compile(r'^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*?))?/?$')

    def github_folder(loc):
        """A folder of a GitHub repository (github.com/OWNER/REPO/tree/BRANCH/PATH, as the browser
        shows it) as an index of what is in it: its zips, and its folders. GitHub's own listing
        of the folder is what is read; the branch is one name without a slash."""
        m = GITHUB_TREE.match(loc)
        if not m:
            return None
        owner, repo, ref, path = m.groups()
        api_url = (f'https://api.github.com/repos/{owner}/{repo}/contents/'
                   f'{urllib.parse.quote(path or "")}?ref={urllib.parse.quote(ref)}')
        return api_url, f'https://github.com/{owner}/{repo}/tree/{ref}'

    def github_items(listing, tree):
        listing = listing if isinstance(listing, list) else []
        # NAME.json beside NAME.zip describes it (read_info()).
        infos = {str(e.get('name', ''))[:-5]: e['download_url'] for e in listing
                 if e.get('type') == 'file' and str(e.get('name', '')).lower().endswith('.json') and e.get('download_url')}
        items = []
        for e in listing:
            name = str(e.get('name', ''))
            if e.get('type') == 'dir':
                items.append({'name': name, 'url': f'{tree}/{urllib.parse.quote(str(e.get("path", name)))}'})
            elif e.get('type') == 'file' and name.lower().endswith('.zip') and e.get('download_url'):
                items.append({'name': name[:-4], 'url': e['download_url'],
                              **({'info': infos[name[:-4]], 'listed': True} if name[:-4] in infos else {})})
        return items

    def read_info(url, refresh):
        """The file that describes a zip ({"name", "description"}, both optional), or {} when it
        cannot be read: a description is help, and one that is wrong does not take its system
        out of the menu."""
        try:
            info = json.loads(fetch(url, refresh).decode('utf-8'))
        except Exception as e:
            api.debug(f'info {url}: {e}')
            return {}
        if not isinstance(info, dict):
            return {}
        return {k: str(info[k])[:MAX_INFO] for k in ('name', 'description') if isinstance(info.get(k), str) and info[k].strip()}

    def node(item, base, depth, refresh):
        """One entry of the setting or of an index, as the page shows it: a system {name,
        url, path}, a folder {name, items}, or {name, error}."""
        name = str(item.get('name') or '')
        try:
            if item.get('info'):
                # The description beside a zip fills in what the entry does not say itself.
                info = read_info(location(base, item['info']), refresh)
                item = {**item, 'description': item.get('description') or info.get('description')}
                # A name taken from a file's name in a listing is the info's to replace; one
                # written in an index is not.
                name = (info.get('name') if item.get('listed') else None) or name or info.get('name', '')
            if 'items' in item:
                return {'name': name or 'systems', 'items': [node(i, base, depth, refresh) for i in item['items']]}
            loc = location(base, item['url'])
            folder = github_folder(loc)
            if folder:
                if depth >= MAX_DEPTH:
                    raise ValueError('folders lead to folders too deep')
                items = github_items(json.loads(fetch(folder[0], refresh).decode('utf-8')), folder[1])
                shown = [node(i, loc, depth + 1, refresh) for i in items]
                # A folder with no zip anywhere below it is not worth a line.
                shown = [n for n in shown if 'url' in n or n.get('items') or n.get('error')]
                return {'name': name or loc.rstrip('/').rsplit('/', 1)[-1], 'items': shown}
            if not is_web(loc) and os.path.isdir(loc):
                return dir_node(name, loc, item.get('description'))
            if isinstance(item.get('path'), str):
                # An entry that says which folder is the system is taken as it says: nothing is
                # downloaded until it is chosen, so a menu of many costs one request, the index.
                # Where it is wrong, the import says so (import_source()).
                # A refresh downloads nothing here, so the copy kept from an earlier
                # import is made out of date: the next import downloads it again (and
                # still falls back on it when the place cannot be reached).
                if refresh and is_web(loc) and os.path.isfile(kept_for(loc)):
                    os.utime(kept_for(loc), (0, 0))
                reached.add(loc)
                return {'name': name or os.path.splitext(os.path.basename(loc.rstrip('/')))[0] or loc,
                        'url': loc, 'path': item['path'].strip('/'),
                        **({'description': item['description']} if item.get('description') else {})}
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

    def list_sources(refresh=False, only=None):
        # `only`: the number of the one source to download anew; the others come from what was kept.
        def mark(n, add):
            # What a source with `add_only` leads to is only added over the files (prepare()).
            if 'url' in n and add:
                addable.add(n['url'])
                n['add_only'] = True
            for sub in n.get('items', []):
                mark(sub, add)
            return n
        return {'sources': [mark(node(s, None, 0, refresh and only in (None, i)), s.get('add_only') is True)
                            for i, s in enumerate(sources)]}

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
        # The page says which line was pressed; add-only is taken only for a location a source
        # with `add_only` led to (the same zip can also be under a source without it).
        adding = asked.get('add_only') is True and loc in addable
        if os.path.isdir(loc):
            # A folder on this machine: the one system in it, zipped as a zip of its own.
            if path not in systems_in_dir(loc):
                raise api.Error(400, f'there is no system in {path or "the top"} of {loc}')
            with zipfile.ZipFile(zip_folder(os.path.join(loc, path)), 'r') as sub:
                return run_import(sub, not adding, asked.get('dry') is True)
        try:
            data = fetch(loc)
            zf = zipfile.ZipFile(io.BytesIO(data))
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            raise api.Error(502, f'could not get {loc}: {e}')
        with zf:
            if path not in systems_in(zf)[0]:
                raise api.Error(400, f'there is no system in {path or "the top"} of {loc}')
            sub = zf if not path else folder_zip(zf, path)
            return run_import(sub, not adding, asked.get('dry') is True)

    def zip_folder(base):
        """A folder as an in-memory zip, its files and folders at the top, as it is (what
        `exclude` leaves out is left out when it is imported). Links are left out."""
        buf = io.BytesIO()
        # strict_timestamps=False: a folder in the Nix store has every file dated 1970, which a zip
        # cannot hold ("ZIP does not support timestamps before 1980"); it is stored as 1980.
        with zipfile.ZipFile(buf, 'w', strict_timestamps=False) as out:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
                for d in dirnames:
                    out.write(os.path.join(dirpath, d), os.path.relpath(os.path.join(dirpath, d), base).replace(os.sep, '/'))
                for fn in sorted(filenames):
                    full = os.path.join(dirpath, fn)
                    if not os.path.islink(full):
                        out.write(full, os.path.relpath(full, base).replace(os.sep, '/'))
        buf.seek(0)
        return buf

    def folder_zip(zf, path):
        """One folder of a zip as a zip of its own, its files at the top, for prepare(). The
        limits are prepare()'s, checked here before anything is copied."""
        prefix = path + '/'
        infos = [i for i in zf.infolist() if i.filename.replace('\\', '/').startswith(prefix) and i.filename.replace('\\', '/') != prefix]
        if (len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED
                or any(i.file_size > MAX_FILE for i in infos)):
            raise api.Error(413, 'that system is too big; nothing was changed')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as out:
            for i in infos:
                out.writestr(i.filename.replace('\\', '/')[len(prefix):], b'' if i.is_dir() else zf.read(i))
        return zipfile.ZipFile(buf)

    def export(req):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            write_tree(zf, here)
        return api.Download(buf.getvalue(), 'application/zip', f'{api.hostname}-system.zip')

    def import_(req):
        try:
            zf = zipfile.ZipFile(io.BytesIO(req.body))
        except zipfile.BadZipFile:
            raise api.Error(400, 'not a valid zip file')
        with zf:
            return run_import(zf, True, req.query.get('dry') == '1')

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
    api.get('sources', lambda req: list_sources(req.query.get('refresh') == '1',
                                                int(req.query['only']) if req.query.get('only', '').isdigit() else None))
    api.post('import-source', import_source)
