{
  description = "eznix — Nix configuration editor for NixOS, nix-darwin and home-manager";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      # No x86_64-darwin: nixpkgs dropped it in 26.11, and listing it fails `nix flake check`.
      systems      = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      mkApp        = drv: bin: { type = "app"; program = "${drv}/bin/${bin}"; };

      perSystem = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          p    = import ./nix/packages.nix { inherit pkgs; version = self.shortRev or "dev"; };
        in {
          packages = {
            default              = p.eznix;
            inherit (p) eznix eznix-terminal eznix-autocomplete;
          };

          apps = {
            default              = mkApp p.eznix           "eznix";
            eznix            = mkApp p.eznix           "eznix";
            eznix-terminal   = mkApp p.eznix-terminal  "eznix-terminal";
            eznix-autocomplete = mkApp p.eznix-autocomplete "eznix-autocomplete";
          };

          devShells.default = pkgs.mkShell { packages = [ p.python pkgs.nix pkgs.nodejs ]; };
        });
    in {
      packages  = builtins.mapAttrs (_: s: s.packages)  perSystem;
      apps      = builtins.mapAttrs (_: s: s.apps)      perSystem;
      devShells = builtins.mapAttrs (_: s: s.devShells) perSystem;

      # pkgs.eznix, and its parts as pkgs.eznix.autocomplete / pkgs.eznix.terminal (also
      # pkgs.eznix-autocomplete, pkgs.eznix-terminal), for a configuration that wants one of
      # them without the modules.
      overlays.default = final: prev:
        let p = import ./nix/packages.nix { pkgs = final; version = self.shortRev or "dev"; };
        in { inherit (p) eznix eznix-terminal eznix-autocomplete; };

      nixosModules.default = import ./nix/nixos.nix self;
      darwinModules.default = import ./nix/darwin.nix self;
      # Standalone home-manager, for a Linux distribution that isn't NixOS.
      homeModules.default = import ./nix/home.nix self;
      homeManagerModules.default = import ./nix/home.nix self;
    };
}
