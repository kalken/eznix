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

          # lib.jsonDir over test/json: files merge, subfolders count, and what is excluded,
          # hidden or disabled stays out (each of those holds an option that doesn't exist).
          # Decided while evaluating, so `nix flake check --no-build` runs it. No raw expression
          # ("_expr") in there: those go through builtins.toFile, which the read-only evaluation
          # of `nix flake check` cannot do.
          checks.json-dir =
            let
              inherit (pkgs) lib;
              got = (lib.evalModules {
                modules = [
                  (self.lib.jsonDir { dir = ./test/json; exclude = [ "skip.json" "vendor/" ]; })
                  {
                    options.t.list = lib.mkOption { type = lib.types.listOf lib.types.int; };
                    options.t.vals = lib.mkOption { type = lib.types.attrsOf lib.types.str; };
                    config._module.args.pkgs = pkgs;
                  }
                ];
              }).config.t;
              want = { list = [ 1 2 ]; vals = { a = "from a"; b = "from b"; }; };
            in
            if got // { list = lib.sort builtins.lessThan got.list; } == want then pkgs.emptyFile
            else throw "lib.jsonDir: got ${builtins.toJSON got}, wanted ${builtins.toJSON want}";
        });
    in {
      packages  = builtins.mapAttrs (_: s: s.packages)  perSystem;
      apps      = builtins.mapAttrs (_: s: s.apps)      perSystem;
      devShells = builtins.mapAttrs (_: s: s.devShells) perSystem;
      checks    = builtins.mapAttrs (_: s: { inherit (s.checks) json-dir; }) perSystem;

      # pkgs.eznix, and its parts as pkgs.eznix.autocomplete / pkgs.eznix.terminal (also
      # pkgs.eznix-autocomplete, pkgs.eznix-terminal), for a configuration that wants one of
      # them without the modules.
      overlays.default = final: prev:
        let p = import ./nix/packages.nix { pkgs = final; version = self.shortRev or "dev"; };
        in { inherit (p) eznix eznix-terminal eznix-autocomplete; };

      # The folder of *.json files eznix edits, as a module for `imports`:
      #   eznix.lib.jsonDir ./eznix
      #   eznix.lib.jsonDir { dir = ./eznix; exclude = [ "notes.json" "vendor" ]; }
      lib.jsonDir = arg: import ./nix/json2nix.nix (if builtins.isAttrs arg then arg else { dir = arg; });

      nixosModules.default = import ./nix/nixos.nix self;
      darwinModules.default = import ./nix/darwin.nix self;
      # Standalone home-manager, for a Linux distribution that isn't NixOS.
      homeModules.default = import ./nix/home.nix self;
      homeManagerModules.default = import ./nix/home.nix self;
    };
}
