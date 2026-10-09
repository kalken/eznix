"""Server half of the documents plugin: lists and reads the *.md files in the flake."""
import os


def setup(api):
    base = os.path.realpath(api.flake)

    def files(req):
        """Every *.md file under the flake as a relative path ("services/nginx/README.md"),
        sorted. A dot-prefixed folder is pruned before os.walk descends into it, and a symlinked
        folder or file is skipped, so this can't follow a `result` symlink into /nix/store or
        loop on a cycle."""
        names = []
        for root, dirs, filenames in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(root, d))]
            for fn in filenames:
                full = os.path.join(root, fn)
                if fn.startswith('.') or not fn.endswith('.md') or os.path.islink(full):
                    continue
                names.append(os.path.relpath(full, base).replace(os.sep, '/'))
        return {'files': sorted(names)}

    def content(req):
        name = req.query.get('name', '')
        parts = name.replace('\\', '/').split('/')
        if not name.endswith('.md') or os.path.isabs(name) or any(p in ('', '.', '..') for p in parts):
            raise api.Error(400, 'not a document')
        full = os.path.realpath(os.path.join(base, name))
        if os.path.commonpath([base, full]) != base or not os.path.isfile(full):
            raise api.Error(400, 'not a document')
        with open(full, encoding='utf-8') as f:
            return {'content': f.read()}

    api.get('files', files)
    api.get('content', content)
