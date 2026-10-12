"""The password plugin: log in with one password from the configuration.

For running eznix by hand, for testing, and wherever a system password can't be checked. An
installed service that uses system passwords can switch it off ([plugin.password] enabled =
false), and then no password kept in a config file can log anyone in.

Settings ([plugin.password] in eznix.toml; `eznix --password PW` sets the first):
  password       the password
  password_file  a file holding it, instead
  username       who it is for (default: whoever runs eznix)

With no password set this plugin does nothing, and eznix falls back to system passwords. It is
also the example of how a plugin adds a way to log in: api.login(check, user).
"""
import getpass
import os
import secrets


def setup(api):
    password = api.config.get('password') or ''
    if not password and api.config.get('password_file'):
        with open(os.path.expanduser(str(api.config['password_file']))) as f:
            password = f.read().strip()
    api.page = {}          # nothing of this reaches the page
    if not password:
        return
    username = str(api.config.get('username') or getpass.getuser())

    def check(name, given):
        # Constant time, both halves always evaluated, so neither a wrong name nor a wrong
        # password answers any faster than the other.
        name_ok = secrets.compare_digest(name.encode(), username.encode())
        pass_ok = secrets.compare_digest(given.encode(), str(password).encode())
        return name_ok and pass_ok

    api.login(check, user=username)
