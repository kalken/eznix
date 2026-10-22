# nix-darwin: eznix for the person at this Mac.
#
# Everything runs as system.primaryUser, in their login session, as two launchd agents: the
# editor and its terminal. Nothing is root, and nothing runs while nobody is logged in. It has
# to be the login session: a rebuild modifies /Applications, which macOS only lets a process
# in the user's own session do (and ask permission for). Login is that user's macOS password.
#
# The terminal's job is not nix-darwin's (see terminalPlist) and deliberately contains no store path. nix-darwin reloads a job whenever its
# definition changes, and has no "don't restart this" switch, so a job naming a store path
# would be restarted by every rebuild -- killing the shell the rebuild runs in. It runs
# /run/current-system/sw/bin/eznix-terminal-start, a script on the system path that holds the
# settings (port, key file, folder, shell), so that the job's own text never changes. The editor's
# job does name store paths, and is meant to restart: an open page then reloads by itself.
self:
{ config, lib, pkgs, ... }:
let
  packages = import ./packages.nix { inherit pkgs; version = self.shortRev or "dev"; };
  user     = config.system.primaryUser;
  home     = config.users.users.${user}.home or "/Users/${user}";
  # "~/..." in flake and configDir is the primary user's home, settled here: the paths also go
  # to the activation script, which runs as root and quotes them, where "~" would be neither.
  tilde    = p: if lib.hasPrefix "~/" p then home + lib.removePrefix "~" p else p;
  cfg      = config.services.eznix // {
    flake     = tilde config.services.eznix.flake;
    configDir = tilde config.services.eznix.configDir;
  };
  stateDir = "${home}/.local/state/eznix";
  terminal = { port = cfg.terminalPort; key_file = "${stateDir}/terminal.key"; };
  label    = "org.nixos.eznix-terminal";      # the name nix-darwin gave it as launchd.user.agents.eznix-terminal

  common = import ./options.nix {
    inherit lib pkgs cfg packages stateDir;
    terminals = { ${user} = terminal; };
    hostNames = let name = config.networking.hostName; in
      lib.optionals (name != null && name != "") [ name "${name}.local" ];
    defaults  = { flake = "/etc/nix-darwin"; theme = "osx"; };
    extra = lib.optionalAttrs cfg.terminal {
      terminal_restart = [ "/bin/launchctl" "kickstart" "-k" "gui/{uid}/${label}" ];
    };
  };

  # A user agent is loaded for whoever logs in at this Mac; only the primary user's does anything.
  onlyFor = ''[ "$(/usr/bin/id -un)" = ${lib.escapeShellArg user} ] || exit 0'';
  # The terminal's job. nix-darwin does not manage it (see postActivation below): it would
  # unload and load it again whenever this text differs, which kills the shell a rebuild runs
  # in, and it has no "leave it running" switch. This text is also kept fixed, whatever the
  # settings: they are in the script it runs, which is reached through the system path.
  terminalPlist = pkgs.writeText "${label}.plist" (lib.generators.toPlist { escape = true; } {
    Label = label;
    ProgramArguments = [ "/bin/sh" "-c"
      "while [ ! -x /run/current-system/sw/bin/eznix-terminal-start ]; do sleep 1; done; exec /run/current-system/sw/bin/eznix-terminal-start" ];
    EnvironmentVariables.PATH = path;
    RunAtLoad = true;
    KeepAlive.SuccessfulExit = false;
    StandardOutPath   = "${home}/Library/Logs/eznix-terminal.log";
    StandardErrorPath = "${home}/Library/Logs/eznix-terminal.log";
  });
  path    = "/run/current-system/sw/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
in
{
  # generateCert was the name of enableHttps until 2026-10; a configuration that still sets it
  # keeps working, with a note to rename it.
  imports = [
    (lib.mkRenamedOptionModule [ "services" "eznix" "generateCert" ] [ "services" "eznix" "enableHttps" ])
    # sections = "collapsed" | "expanded" became collapseLevel, a number, on 2026-10-12.
    (lib.mkChangedOptionModule [ "services" "eznix" "sections" ] [ "services" "eznix" "collapseLevel" ]
      (config: if config.services.eznix.sections == "expanded" then null else 3))
  ];

  options.services.eznix = common.options;

  config = lib.mkIf cfg.enable {
    assertions = common.assertions ++ [ {
      assertion = (config.system.primaryUser or null) != null;
      message   = "services.eznix needs system.primaryUser: that is who it runs as.";
    } ];

    # With no password set, the login is the primary user's own macOS password.
    services.eznix.users = lib.mkIf (cfg.password == null && cfg.passwordFile == null) (lib.mkDefault [ user ]);

    # eznix-terminal has to be on the system path for the terminal's job (see above).
    environment.systemPackages = [
      packages.eznix-terminal
      (common.autocompleteCommand "$HOME/.local/state/eznix/autocomplete")
    ] ++ lib.optional cfg.terminal (pkgs.writeShellScriptBin "eznix-terminal-start" ''
      # What the terminal's job runs (see there): this changes with the settings, the job does not.
      ${onlyFor}
      umask 077; mkdir -p ${lib.escapeShellArg stateDir}
      # The key is made here, before the terminal starts; the editor only ever reads it.
      [ -s ${lib.escapeShellArg terminal.key_file} ] || /usr/bin/openssl rand -hex 32 > ${lib.escapeShellArg terminal.key_file}
      exec /run/current-system/sw/bin/eznix-terminal ${common.terminalArgs terminal}
    '');

    # nix-darwin only runs the activation scripts it knows by name; a custom name is never run.
    system.activationScripts.postActivation.text = common.configDirScript + ''
      chown -R ${lib.escapeShellArg user} ${lib.escapeShellArg cfg.configDir}
    '' + ''
      # The terminal's job, installed here and not through launchd.user.agents so that a rebuild
      # never reloads it (see terminalPlist). The file is kept up to date; a job that is loaded
      # is left running, and the new text counts from its next load, as with
      # restartIfChanged = false on NixOS. Loaded only when it is not.
      agent=${lib.escapeShellArg "${home}/Library/LaunchAgents/${label}.plist"}
      uid=$(id -u ${lib.escapeShellArg user})
      ${if cfg.terminal then ''
        sudo --user=${lib.escapeShellArg user} -- mkdir -p "$(dirname "$agent")" ${lib.escapeShellArg "${home}/Library/Logs"}
        cmp -s ${terminalPlist} "$agent" || sudo --user=${lib.escapeShellArg user} -- cp -f ${terminalPlist} "$agent"
        launchctl asuser "$uid" sudo --user=${lib.escapeShellArg user} -- launchctl list ${label} >/dev/null 2>&1 \
          || launchctl asuser "$uid" sudo --user=${lib.escapeShellArg user} -- launchctl load -w "$agent"
      '' else ''
        if [ -e "$agent" ]; then
          launchctl asuser "$uid" sudo --user=${lib.escapeShellArg user} -- launchctl unload "$agent" || true
          sudo --user=${lib.escapeShellArg user} -- rm -f "$agent"
        fi
      ''}
    '' + lib.optionalString cfg.trustCert ''
      # trustCert. The authority is made here as well as by the editor's job, as the user, so
      # that there is one to trust at the very rebuild that switches this on. Firefox gets it
      # in its profiles (it reads nothing else); everything else reads the keychain.
      #
      # macOS only lets a trusted root be added with a person's approval, a password dialog,
      # root or not. Activation runs in the terminal of whoever typed darwin-rebuild, where
      # the dialog can appear; from eznix's own terminal panel there is no session to show it
      # in, and then this says what to run by hand. It never fails the activation, and
      # verify-cert makes it happen once.
      /usr/bin/sudo -H -u ${lib.escapeShellArg user} /bin/sh -c ${lib.escapeShellArg ''
        umask 077; mkdir -p ${lib.escapeShellArg stateDir}
        ${common.generateCa "${packages.eznix}/bin/eznix"}
        ${common.trustCertScript {
          nssdb           = false;
          firefoxProfiles = ''"$HOME/Library/Application Support/Firefox/Profiles"/*/'';
        }}
      ''} || true
      ca=${lib.escapeShellArg "${stateDir}/ca.pem"}
      if [ -f "$ca" ] && ! /usr/bin/security verify-cert -c "$ca" >/dev/null 2>&1; then
        echo "eznix: trusting its certificate authority (macOS may ask for your password)..." >&2
        /usr/bin/security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$ca" \
          || echo "eznix: could not do that from here. Run this once in Terminal:
  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $ca" >&2
      fi
    '';

    launchd.user.agents.eznix.serviceConfig = {
      ProgramArguments = [ "/bin/sh" "-c" ''
        ${onlyFor}
        umask 077; mkdir -p ${lib.escapeShellArg stateDir}
        ${common.generateCa "${packages.eznix}/bin/eznix"}
        exec ${packages.eznix}/bin/eznix --config ${common.toml}
      '' ];
      EnvironmentVariables.PATH = path;
      RunAtLoad = true;
      KeepAlive.SuccessfulExit = false;
      # The logs are in the user's own Library, not /tmp, which every account on the Mac can read.
      StandardOutPath   = "${home}/Library/Logs/eznix.log";
      StandardErrorPath = "${home}/Library/Logs/eznix.log";
    };
  };
}
