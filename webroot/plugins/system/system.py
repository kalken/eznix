"""Server half of the system plugin: the whole flake as a zip, out and back in.

  GET  export           download the flake as a zip
  POST import           replace the flake's files with an uploaded zip's
  GET  backups          the automatic backups, newest first
  POST restore?name=N   replace the flake's files with a backup's

Only the requests are here. What they do is in backup.py, next to this file, which is also the
eznix-backup command: read its top for how import and restore behave, and why.

Settings ([plugin.system] in eznix.toml):
  backups   how many backups to keep (default 5; 0: none)
  dotfiles  include dot-files and dot-folders in an export (default false)
  exclude   file names to leave out of an export, anywhere in the tree
"""
import importlib.util
import io
import os
import zipfile

# By path: eznix loads this file by path too (_load_plugins()), so its folder is not somewhere
# `import backup` would look.
_spec = importlib.util.spec_from_file_location(
    'eznix_plugin_system_backup', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup.py'))
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


def setup(api):
    tree = backup.Tree(api.flake, os.path.join(api.state_dir, 'system-backups'),
                       api.config.get('backups', 5), api.config.get('dotfiles', False),
                       api.config.get('exclude', []))
    api.page = {'backups': tree.keep > 0}

    def apply(zf):
        try:
            return tree.apply(zf)
        except backup.BadZip as e:
            raise api.Error(400, str(e))

    def export(req):
        buf = io.BytesIO()
        tree.export(buf)
        return api.Download(buf.getvalue(), 'application/zip', f'{api.hostname}-system.zip')

    def import_(req):
        try:
            zf = zipfile.ZipFile(io.BytesIO(req.body))
        except zipfile.BadZipFile:
            raise api.Error(400, 'not a valid zip file')
        with zf:
            tree.snapshot('before import')
            return apply(zf)

    def restore(req):
        name = req.query.get('name', '')
        path = os.path.join(tree.backup_dir, name)
        if not name or '/' in name or '\\' in name or name in ('.', '..') or not os.path.isfile(path):
            raise api.Error(400, 'no such backup')
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise api.Error(500, 'backup is not a valid zip file')
        # The backup being restored may itself be pruned by the snapshot taken here, so it is
        # open before that happens.
        with zf:
            tree.snapshot('before restore')
            return apply(zf)

    api.get('export', export)
    api.get('backups', lambda req: {'backups': tree.listing()})
    api.post('import', import_)
    api.post('restore', restore)
