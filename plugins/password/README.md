# password

Log in to eznix with one password of its own, in place of a system password.

## ✨ What it is for

- Running eznix by hand, and trying it out
- A machine where a system password cannot be checked (home-manager on another Linux)

## 🚀 Usage

With the nix-darwin and home-manager modules, through eznix's own options (the NixOS
module logs in with system passwords and has no such option):

```nix
services.eznix.passwordFile = "/home/alice/.config/eznix-password";
```

By hand: `eznix --password something`, or in `eznix.toml`:

```toml
[plugin.password]
password_file = "/home/alice/.config/eznix-password"
```

## 📋 Options

| Option | Default | |
|---|---|---|
| `password` | | the password |
| `password_file` | | a file holding it, instead |
| `username` | whoever runs eznix | who it is for |
| `enabled` | `true` | `false` leaves the plugin out, so that no password kept in a file can log anyone in |

## 📝 Notes

- With no password set it does nothing, and eznix asks for a system password.
- A password in the configuration ends up in the Nix store, readable by everyone on the
  machine. Use the file.
