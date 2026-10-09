{
  description = "This machine, configured in eznix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    eznix = {
      url = "github:kalken/eznix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, eznix, ... }: {
    # "default" and not this machine's name, so nothing here has to be changed. It is why a
    # rebuild names it:  sudo nixos-rebuild switch --flake /etc/nixos#default
    nixosConfigurations.default = nixpkgs.lib.nixosSystem {
      modules = [
        # What the installer wrote, kept as it is: the boot loader, the disks (it imports
        # hardware-configuration.nix), your account. Settings can move from there into eznix
        # one at a time; the same one set differently in both places is an error.
        ./configuration.nix
        eznix.nixosModules.default       # the editor
        (eznix.lib.jsonDir ./eznix)      # the configuration: the *.json files it edits
      ];
    };
  };
}
