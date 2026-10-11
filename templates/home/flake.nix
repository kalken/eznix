{
  description = "My home, configured in eznix";

  inputs = {
    # The current stable release, and home-manager's branch for it: the two go together. For
    # newer packages sooner, with more changes between rebuilds, the rolling pair is
    # "github:NixOS/nixpkgs/nixos-unstable" and "github:nix-community/home-manager".
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    eznix = {
      url = "github:kalken/eznix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, home-manager, eznix, ... }: {
    # "default" and not your name, so only the line below may need changing. It is why a
    # rebuild names it:  home-manager switch --flake "$HOME/.config/home-manager#default"
    homeConfigurations.default = home-manager.lib.homeManagerConfiguration {
      pkgs = nixpkgs.legacyPackages.x86_64-linux;     # aarch64-linux on an ARM machine
      modules = [
        eznix.homeModules.default        # the editor
        (eznix.lib.jsonDir ./eznix)      # the configuration: the *.json files it edits
      ];
    };
  };
}
