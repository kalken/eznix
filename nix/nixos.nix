# NixOS: eznix as a service.
#
# Nothing here runs as root. The editor runs as its own account, "eznix". Every person in
# `users` logs in with their system password and gets a terminal of their own, a separate unit
# running as them; a rebuild from there goes through sudo like anywhere else.
#
# Two things an unprivileged service can't do by itself, and how each is given to it:
#   check someone's password    a small setuid helper, runnable by the eznix group only
#   restart someone's terminal  a sudo rule for exactly those units
#
# Evaluated, never run: no part of this has been started on a real NixOS machine yet.
self:
{ config, lib, pkgs, ... }:
let
  cfg      = config.services.eznix;
  packages = import ./packages.nix { inherit pkgs; version = self.shortRev or "dev"; };
  stateDir = "/var/lib/eznix";

  termUnit = user: "eznix-terminal-${user}";
  termDir  = user: "/run/eznix-terminal/${user}";
  terminals = lib.listToAttrs (lib.imap0 (i: user: {
    name  = user;
    value = { port = cfg.terminalPort + i; key_file = "${termDir user}/key"; };
  }) cfg.users);

  sudo      = "/run/wrappers/bin/sudo";
  systemctl = "/run/current-system/sw/bin/systemctl";

  # Checks a password for the service: user and password on stdin, one per line; exit 0 when
  # right. It names the Python interpreter itself, with -I: a wrapper script in between would
  # be a shell, and a shell drops setuid privileges. It answers only for the allowed users.
  authHelper = pkgs.writeScript "eznix-auth" ''
    #!${pkgs.python3}/bin/python3 -I
    import os, sys
    sys.path[:0] = ${builtins.toJSON (lib.splitString ":" (pkgs.python3.pkgs.makePythonPath [ pkgs.python3.pkgs.python-pam ]))}
    ALLOWED = ${builtins.toJSON cfg.users}
    def main():
        try:
            os.setgid(0); os.setuid(0)
        except OSError:
            return 2
        lines = sys.stdin.read(4096).split("\n")
        if len(lines) < 2 or lines[0] not in ALLOWED:
            return 1
        import pam
        return 0 if pam.pam().authenticate(lines[0], lines[1]) else 1
    sys.exit(main())
  '';

  common = import ./options.nix {
    inherit lib pkgs cfg packages stateDir terminals;
    defaults = { flake = "/etc/nixos"; theme = "nixos"; };
    extra = {
      auth_helper = "/run/wrappers/bin/eznix-auth";
    } // lib.optionalAttrs cfg.terminal {
      terminal_restart = [ sudo "-n" systemctl "restart" "eznix-terminal-{user}.service" ];
    };
  };
in
{
  options.services.eznix = common.options // {
    openFirewall = lib.mkOption {
      type        = lib.types.bool;
      default     = false;
      description = "Open the editor's port in the firewall. The terminals' ports are never opened.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = common.assertions ++ [
      {
        assertion = cfg.users != [ ];
        message   = "services.eznix.users needs at least one name: they are who can log in, and whose terminals it runs.";
      }
      {
        assertion = cfg.password == null && cfg.passwordFile == null;
        message   = "services.eznix on NixOS logs people in with their system passwords; password and passwordFile are for the home-manager and nix-darwin modules.";
      }
    ];

    environment.systemPackages = [ (common.autocompleteCommand "${stateDir}/autocomplete") common.backupCommand ];
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];

    users.users.eznix = {
      isSystemUser = true;
      group        = "eznix";
      home         = stateDir;
    };
    # The people who log in share the *.json files with the service (their own terminal and
    # git edit the same files), and write the suggestions it reads.
    users.groups.eznix.members = cfg.users;

    security.wrappers.eznix-auth = {
      source      = authHelper;
      owner       = "root";
      group       = "eznix";
      setuid      = true;
      permissions = "u+rx,g+x";
    };
    security.sudo.extraRules = lib.mkIf cfg.terminal [ {
      users    = [ "eznix" ];
      commands = map (user: {
        command = "${systemctl} restart ${termUnit user}.service";
        options = [ "NOPASSWD" ];
      }) cfg.users;
    } ];

    # The one place eznix takes ownership of: its own folder of *.json files, group-shared
    # (setgid, and a default ACL so a file is writable by the group whoever made it). Nothing
    # else in the flake is touched.
    system.activationScripts.eznix = {
      deps = [ "users" "groups" ];
      text = common.configDirScript + ''
        chown -R eznix:eznix ${lib.escapeShellArg cfg.configDir}
        chmod -R g+rwX ${lib.escapeShellArg cfg.configDir}
        chmod g+s ${lib.escapeShellArg cfg.configDir}
        ${pkgs.acl}/bin/setfacl -R -m g:eznix:rwX -d -m g:eznix:rwX ${lib.escapeShellArg cfg.configDir} 2>/dev/null || true
      '';
    };

    systemd.tmpfiles.rules = [ "d ${stateDir}/autocomplete 2775 eznix eznix -" ];

    systemd.services = {
      eznix = {
        description = "eznix configuration editor";
        wantedBy    = [ "multi-user.target" ];
        after       = [ "network.target" ];
        serviceConfig = {
          User               = "eznix";
          Group              = "eznix";
          UMask              = "0002";      # its files stay writable by the group
          StateDirectory     = "eznix";
          StateDirectoryMode = "0750";
          ExecStartPre       = lib.mkIf cfg.generateCert
            (pkgs.writeShellScript "eznix-certificate" (common.generateCa "${packages.eznix}/bin/eznix"));
          ExecStart          = "${packages.eznix}/bin/eznix --config ${common.toml}";
          Restart            = "on-failure";
        };
      };
    } // lib.optionalAttrs cfg.terminal (lib.mapAttrs' (user: t: lib.nameValuePair (termUnit user) {
      description      = "eznix terminal for ${user}";
      wantedBy         = [ "multi-user.target" ];
      # It forks the shell as its own child: restarting the unit kills whatever runs there,
      # most likely the very rebuild that would be doing the restarting. The page offers a
      # restart when the running terminal is out of date.
      restartIfChanged = false;
      serviceConfig = {
        User         = user;
        # The secret between this terminal and the editor: readable by this user and, through
        # its group, by the service -- not by the other users, who could otherwise reach each
        # other's shells over loopback.
        ExecStartPre = "+" + pkgs.writeShellScript "eznix-terminal-key-${user}" ''
          mkdir -p -m 755 /run/eznix-terminal
          mkdir -p ${termDir user}
          if [ ! -s ${t.key_file} ]; then
            ( umask 077; ${pkgs.openssl}/bin/openssl rand -hex 32 > ${t.key_file} )
          fi
          chown -R ${lib.escapeShellArg user}:eznix ${termDir user}
          chmod 750 ${termDir user}
          chmod 640 ${t.key_file}
        '';
        ExecStart    = "${packages.eznix-terminal}/bin/eznix-terminal ${common.terminalArgs t}";
        Restart      = "on-failure";
      };
    }) terminals);
  };
}
