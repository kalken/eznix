"""Server half of the uploads plugin: puts a file the browser sends into a folder that the
configuration names, and lists and removes what is there.

  GET  files                  for each target, in the order they are configured: the files in
                              its folder (name, size)
  POST upload?target=N&name=F the request body becomes file F in target N's folder, replacing
                              a file of that name
  POST delete?target=N&name=F removes file F from target N's folder

Nothing is written but to a folder a target names, and only as a plain file name directly in
it: no path, no dot-file, and one of the target's `extensions`. The file is written beside the
final one with its mode set before it has any content, then renamed into place, so a reader
never sees half a file or one more readable than `mode` says. A zip is opened before it is
kept, and one that is not a zip, or has a path leading out of its folder (absolute, or with
`..`), is refused; it is never unpacked here.

Settings ([plugin.uploads] in eznix.toml):
  targets   a list; none unless set, and then nothing of the plugin is seen. Each entry is a
            button in the header:
              name        what the button says
              dir         the folder files go in (it has to exist, and eznix has to be able to
                          write in it: eznix does not run as root, and does not need to)
              mode        the file mode of what is kept, as octal text; default "0600"
              extensions  how the file names may end; default [".zip"]
              max_size    the biggest file, in megabytes; default 16
"""
import os
import io
import stat
import tempfile
import zipfile

MEGABYTE = 1024 * 1024


def _plain_name(name):
    return bool(name) and name not in ('.', '..') and not name.startswith('.') \
        and not any(c in name for c in '/\\\0')


def _checked_zip(body):
    """Raises ValueError, saying why, unless body is a zip whose names all stay inside the
    folder it would be unpacked in."""
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            for entry in zf.namelist():
                parts = entry.replace('\\', '/').split('/')
                if entry.startswith(('/', '\\')) or '..' in parts or parts[0].endswith(':'):
                    raise ValueError('the zip holds a path that leads out of its folder: ' + entry)
    except zipfile.BadZipFile:
        raise ValueError('not a valid zip file')


def setup(api):
    targets = []
    for entry in api.config.get('targets', []):
        if not isinstance(entry, dict) or not str(entry.get('dir') or '').startswith('/'):
            api.debug(f'target skipped, it needs a "dir" that is a full path: {entry!r}')
            continue
        try:
            mode = int(str(entry.get('mode') or '0600'), 8) & 0o777
        except ValueError:
            api.debug(f'target skipped, "mode" is not octal: {entry!r}')
            continue
        endings = [str(e) for e in entry.get('extensions', ['.zip']) if str(e)]
        targets.append({
            'name': str(entry.get('name') or entry['dir']), 'dir': str(entry['dir']), 'mode': mode,
            'extensions': endings, 'max_size': int(entry.get('max_size', 16)) * MEGABYTE,
        })
    # What the page is told: what to show of each, for the menu's headings.
    api.page = {'targets': [{'name': t['name'], 'dir': t['dir'], 'extensions': t['extensions'],
                             'max_size': t['max_size']} for t in targets]}

    def target_of(req):
        try:
            return targets[int(req.query.get('target', ''))]
        except (ValueError, IndexError):
            raise api.Error(400, 'no such target')

    def name_of(req, target):
        name = req.query.get('name', '')
        if not _plain_name(name) or not name.endswith(tuple(target['extensions'])):
            raise api.Error(400, 'the name has to be a plain file name ending in ' + ' or '.join(target['extensions']))
        return name

    def listing(target):
        try:
            names = sorted(os.listdir(target['dir']))
        except OSError:
            return []
        found = []
        for name in names:
            info = os.lstat(os.path.join(target['dir'], name))
            if stat.S_ISREG(info.st_mode) and _plain_name(name) and name.endswith(tuple(target['extensions'])):
                found.append({'name': name, 'size': info.st_size})
        return found

    def files(req):
        return {'targets': [listing(t) for t in targets]}

    def upload(req):
        target = target_of(req)
        name = name_of(req, target)
        if not req.body:
            raise api.Error(400, 'the file is empty')
        if len(req.body) > target['max_size']:
            raise api.Error(413, f'the file is over {target["max_size"] // MEGABYTE} MB')
        if name.endswith('.zip'):
            try:
                _checked_zip(req.body)
            except ValueError as e:
                raise api.Error(400, str(e))
        try:
            # mkstemp makes the file 0600, owned by eznix and nobody else's, before any content
            fd, temp = tempfile.mkstemp(prefix='.upload-', dir=target['dir'])
        except OSError:
            raise api.Error(403, 'eznix may not write in ' + target['dir'])
        try:
            with os.fdopen(fd, 'wb') as handle:
                os.fchmod(handle.fileno(), target['mode'])
                handle.write(req.body)
            os.replace(temp, os.path.join(target['dir'], name))
        except OSError as e:
            try:
                os.remove(temp)
            except OSError:
                pass
            raise api.Error(500, 'could not keep the file: ' + e.strerror)
        api.debug(f'kept {name} in {target["dir"]}')
        return {'kept': name}

    def delete(req):
        target = target_of(req)
        name = name_of(req, target)
        path = os.path.join(target['dir'], name)
        if not os.path.isfile(path) or os.path.islink(path):
            raise api.Error(400, 'not a file of this target')
        try:
            os.remove(path)
        except PermissionError:
            raise api.Error(403, 'eznix may not delete ' + name)
        return {'deleted': name}

    api.get('files', files)
    api.post('upload', upload)
    api.post('delete', delete)
