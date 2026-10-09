{
  description = "This Mac, configured in eznix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    eznix = {
      url = "github:kalken/eznix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, nix-darwin, eznix, ... }: {
    # "default" and not this Mac's name, so nothing here has to be changed. It is why a rebuild
    # names it:  sudo darwin-rebuild switch --flake "$HOME/.config/nix-darwin#default"
    darwinConfigurations.default = nix-darwin.lib.darwinSystem {
      modules = [
        eznix.darwinModules.default      # the editor
        (eznix.lib.jsonDir ./eznix)      # the configuration: the *.json files it edits
      ];
    };
  };
}
