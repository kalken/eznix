# The three programs. `version` ends up in the page's status bar.
{ pkgs, version ? "dev" }:
rec {
  # nixpkgs builds python-pam against its own libpam, which on macOS is a bare OpenPAM in the Nix
  # store: the library path it's patched to doesn't exist there (so every login just failed), and
  # even a working one would know nothing of the system's own /etc/pam.d. Point it at the system
  # library instead. pam_misc is Linux-PAM only; python-pam copes with it being absent.
  python-pam = ps:
    if !pkgs.stdenv.hostPlatform.isDarwin then ps.python-pam
    else ps.python-pam.overridePythonAttrs (_: {
      postPatch = ''
        substituteInPlace src/pam/__internals.py \
          --replace-fail 'find_library("pam")' '"/usr/lib/libpam.dylib"' \
          --replace-fail 'find_library("pam_misc")' 'None'
      '';
      buildInputs = [ ];
      doCheck     = false;
    });

  # python-pam: system-password login. cryptography: --generate-ca.
  python = pkgs.python3.withPackages (ps: [ (python-pam ps) ps.cryptography ]);

  # The editor: the server and the page (plugins included).
  eznix = pkgs.stdenv.mkDerivation {
    pname = "eznix";
    inherit version;
    src = pkgs.lib.fileset.toSource {
      root    = ../.;
      fileset = pkgs.lib.fileset.unions [ ../bin/eznix.py ../webroot ];
    };
    nativeBuildInputs = [ pkgs.makeWrapper ];
    # pkgs.eznix.autocomplete, pkgs.eznix.terminal: the parts, for installing one by itself.
    passthru = { autocomplete = eznix-autocomplete; terminal = eznix-terminal; };
    meta = {
      description = "Web-based Nix configuration editor for NixOS, nix-darwin and home-manager";
      license     = pkgs.lib.licenses.mit;
      mainProgram = "eznix";
    };
    installPhase = ''
      mkdir -p $out/share/eznix
      cp bin/eznix.py $out/share/eznix/
      cp -r webroot $out/share/eznix/webroot
      # Run by hand (nix run), eznix starts its own terminal and looks for it next to itself.
      ln -s ${eznix-terminal}/share/eznix-terminal/eznix-terminal.py $out/share/eznix/eznix-terminal.py
      echo -n "${version}" > $out/share/eznix/webroot/VERSION
      cp ${pkgs.nixos-icons}/share/icons/hicolor/scalable/apps/nix-snowflake.svg \
        $out/share/eznix/webroot/favicon.svg
      makeWrapper ${python}/bin/python3 $out/bin/eznix --add-flags $out/share/eznix/eznix.py
    '';
  };

  # The terminal, a derivation of its own so that a change to the page doesn't change it: the
  # modules never restart a running terminal by themselves, and the page tells a terminal that
  # is out of date by this file's hash.
  #
  # No version in it, for the same reason: `version` is the commit eznix was built from, so
  # with it this would be a new store path after every commit, whatever the commit touched.
  # NixOS and home-manager name that path in the terminal's unit, and then report the unit as
  # changed and in need of a restart on every update -- while the page, which compares the
  # file itself, rightly says nothing.
  eznix-terminal = pkgs.stdenv.mkDerivation {
    name = "eznix-terminal";
    src        = ../bin/eznix-terminal.py;
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram  = "eznix-terminal";
    installPhase = ''
      install -Dm644 $src $out/share/eznix-terminal/eznix-terminal.py
      makeWrapper ${pkgs.python3}/bin/python3 $out/bin/eznix-terminal \
        --add-flags $out/share/eznix-terminal/eznix-terminal.py
    '';
  };

  # The generator of the editor's suggestions, usable by itself on any flake:
  #   eznix-autocomplete --flake DIR --output DIR
  # (The modules put a command of the same name on PATH that already knows both.)
  eznix-autocomplete = pkgs.writeShellApplication {
    name          = "eznix-autocomplete";
    runtimeInputs = [ pkgs.nix pkgs.python3 ];
    text          = ''exec python3 "${../bin/eznix-autocomplete.py}" "$@"'';
  };
}
