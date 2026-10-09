# eznix

Change the settings of a Nix system in your browser, instead of editing files by hand. It
works on NixOS, on a Mac (nix-darwin) and on other Linux (home-manager).

## Install

You need Nix. NixOS has it. On a Mac or another Linux, install it first, with either
[Determinate Nix](https://docs.determinate.systems/determinate-nix/) or the
[official installer](https://nixos.org/download); both work. Then copy the lines for your
system into a terminal.

**NixOS** (your `configuration.nix` is kept as it is)

```sh
cd /etc/nixos
sudo nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#nixos
sudo sed -i "s/YOUR-USER-NAME/$USER/" eznix/system.json
sudo nixos-rebuild switch --flake "/etc/nixos#default"
```

**Mac**

```sh
mkdir -p ~/.config/nix-darwin && cd ~/.config/nix-darwin
nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#darwin
sed -i '' "s/YOUR-USER-NAME/$USER/" eznix/system.json
sudo nix --extra-experimental-features 'nix-command flakes' run nix-darwin -- switch --flake "$HOME/.config/nix-darwin#default"
```

**Other Linux**

```sh
mkdir -p ~/.config/home-manager && cd ~/.config/home-manager
nix --extra-experimental-features 'nix-command flakes' flake init -t github:kalken/eznix#home
sed -i "s/YOUR-USER-NAME/$USER/g" eznix/home.json
echo "a-password-of-your-own" > ~/.config/eznix-password && chmod 600 ~/.config/eznix-password
nix --extra-experimental-features 'nix-command flakes' run home-manager/master -- switch --flake "$HOME/.config/home-manager#default"
```

The last line takes a few minutes the first time. When it is done, open
http://localhost:9090 in a browser on that computer and log in with your user name and your
usual password (on other Linux: the password you chose above).

## Use

1. Press **Generate Autocomplete** at the bottom once, and wait for it to finish. eznix can then
   suggest settings and programs as you type.
2. Change what you want. To add a setting, type its name in the field that says
   "Add option path…".
3. Press **Save**.
4. Press **Rebuild** at the bottom. It asks for your password in the terminal there, and
   your changes are in effect when it finishes.

Nothing on your computer changes until you have saved and rebuilt.

## More

[REFERENCE.md](REFERENCE.md) has the rest: opening eznix from another computer, HTTPS, every
setting, buttons, plugins, themes, and adding eznix to a configuration you already keep as a
flake.
