# home-manager: eznix for one person, on a Linux distribution that isn't NixOS.
#
# There is no root-owned system for Nix to manage there, only this user's environment, so the
# editor and its terminal are two systemd *user* services, both running as that user, with
# their state under the home folder. Nothing is root at any point; rebuilding is
# `home-manager switch`, no sudo. It edits a standalone home-manager flake, and the suggestions
# come from its homeConfigurations (eznix-autocomplete --type home).
#
# Evaluated, never run: no part of this has been started on a real machine yet.
self:
{ config, lib, pkgs, ... }:
let
  # "~/..." in flake and configDir is the home folder, settled here: the scripts these paths go
  # to quote them, so no shell would expand it.
  tilde    = p: if lib.hasPrefix "~/" p then config.home.homeDirectory + lib.removePrefix "~" p else p;
  cfg      = config.services.eznix // {
    flake     = tilde config.services.eznix.flake;
    configDir = tilde config.services.eznix.configDir;
  };
  packages = import ./packages.nix { inherit pkgs; version = self.shortRev or "dev"; };
  stateDir = "${config.xdg.stateHome}/eznix";
  terminal = { port = cfg.terminalPort; key_file = "${stateDir}/terminal.key"; };

  common = import ./options.nix {
    inherit lib pkgs cfg packages stateDir;
    terminals = { ${config.home.username} = terminal; };
    defaults  = { flake = "${config.xdg.configHome}/home-manager"; theme = "nixos"; };
    prog      = config.programs.eznix;
    extra = lib.optionalAttrs cfg.terminal {
      terminal_restart = [ "systemctl" "--user" "restart" "eznix-terminal.service" ];
    };
  };

  # A user unit starts with next to nothing on PATH.
  path = "${lib.makeBinPath [ pkgs.coreutils pkgs.openssl ]}:${config.home.profileDirectory}/bin:/run/current-system/sw/bin:/usr/local/bin:/usr/bin:/bin";
in
{
  # generateCert was the name of enableHttps until 2026-10; a configuration that still sets it
  # keeps working, with a note to rename it.
  imports = [
    (lib.mkRenamedOptionModule [ "services" "eznix" "generateCert" ] [ "services" "eznix" "enableHttps" ])
    # sections = "collapsed" | "expanded" became collapseLevel, a number, on 2026-10-12.
    (lib.mkChangedOptionModule [ "services" "eznix" "sections" ] [ "services" "eznix" "collapseLevel" ]
      (config: if config.services.eznix.sections == "expanded" then null else 3))
    # The menu entry opened a Chromium-family browser in app mode until 2026-10-15; it opens
    # the default browser now.
    (lib.mkRemovedOptionModule [ "programs" "eznix" "browser" ] "The entry opens the default browser.")
    (lib.mkRemovedOptionModule [ "programs" "eznix" "windowClass" ] "The entry opens the default browser, in a tab of its own.")
  ];

  options.services.eznix = common.options;

  options.programs.eznix = common.programOptions;

  config = lib.mkMerge [
   (lib.mkIf (common.apps != [ ]) { home.packages = common.apps; })
   (lib.mkIf cfg.enable {
    assertions = common.assertions ++ [
      {
        assertion = pkgs.stdenv.hostPlatform.isLinux;
        message   = "The eznix home-manager module is for Linux (it sets up systemd user services). On macOS use the nix-darwin module, darwinModules.default.";
      }
      {
        # No system passwords here. A service that isn't root can at best check its own
        # user's, and on a distribution that isn't NixOS not even that: nixpkgs' PAM library
        # reads the host's /etc/pam.d, which on Debian 13 it cannot parse (@include is
        # Debian's own addition) and whose modules it cannot load (tried 2026-10-15). It
        # works where the host is NixOS, which has a module of its own for that; documenting
        # users as working on NixOS alone was the first answer, and the user asked why it was
        # there at all. Calling the host's own unix_chkpwd, as an auth_helper for one's own
        # password, was talked through and not built.
        assertion = cfg.users == [ ];
        message   = "services.eznix.users (system passwords) does not work with home-manager: set passwordFile (or password) instead. On NixOS, the NixOS module has system passwords.";
      }
      {
        assertion = cfg.password != null || cfg.passwordFile != null;
        message   = "services.eznix needs a way to log in: set passwordFile (or password).";
      }
    ];

    home.packages = [ (common.autocompleteCommand "${stateDir}/autocomplete") ];

    home.activation.eznix = lib.hm.dag.entryAfter [ "writeBoundary" ] common.configDirScript;

    systemd.user.services.eznix = {
      Unit = { Description = "eznix configuration editor"; After = [ "network.target" ]; };
      Service = {
        Environment  = [ "PATH=${path}" ];
        ExecStartPre = pkgs.writeShellScript "eznix-setup" ''
          umask 077; mkdir -p ${lib.escapeShellArg stateDir}
          ${common.generateCa "${packages.eznix}/bin/eznix"}
          ${lib.optionalString cfg.trustCert (common.trustCertScript {
            firefoxProfiles = ''"$HOME"/.mozilla/firefox/*/ "$HOME"/.config/mozilla/firefox/*/'';
          })}
        '';
        ExecStart    = "${packages.eznix}/bin/eznix --config ${common.toml}";
        Restart      = "on-failure";
      };
      Install.WantedBy = [ "default.target" ];
    };

    # Not restarted by `home-manager switch` (X-SwitchMethod = keep-old): it forks the shell as
    # its own child, so restarting it kills whatever runs there -- most likely the very switch
    # that would be doing the restarting. The page offers a restart when it is out of date.
    systemd.user.services.eznix-terminal = lib.mkIf cfg.terminal {
      Unit = { Description = "eznix terminal"; X-SwitchMethod = "keep-old"; };
      Service = {
        Environment  = [ "PATH=${path}" ];
        # The key is made here, before the terminal starts; the editor only ever reads it.
        ExecStartPre = pkgs.writeShellScript "eznix-terminal-key" ''
          umask 077; mkdir -p ${lib.escapeShellArg stateDir}
          [ -s ${lib.escapeShellArg terminal.key_file} ] || openssl rand -hex 32 > ${lib.escapeShellArg terminal.key_file}
        '';
        ExecStart    = "${packages.eznix-terminal}/bin/eznix-terminal ${common.terminalArgs terminal}";
        Restart      = "on-failure";
      };
      Install.WantedBy = [ "default.target" ];
    };
   })
  ];
}
