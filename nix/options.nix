# What the three modules share: the options, and the eznix.toml made from them.
#
#   packages   nix/packages.nix, evaluated
#   defaults   { flake, theme }: what differs by platform
#   stateDir   where this install keeps its state (null: the server's own default, ~/.local/state/eznix)
#   terminals  user -> { port, key_file }: terminals run by the module, one per user
#   extra      more top-level eznix.toml keys from the module (terminal_restart, auth_helper, ...)
{ lib, pkgs, cfg, packages, defaults, stateDir, terminals ? { }, extra ? { } }:
let
  inherit (lib) mkOption mkEnableOption types;

  isLocal = builtins.elem cfg.listen [ "127.0.0.1" "::1" "localhost" ];

  themesDir  = pkgs.linkFarm "eznix-themes"
    (lib.mapAttrsToList (name: path: { name = "${name}.css"; inherit path; }) cfg.themes);
  pluginsDir = pkgs.linkFarm "eznix-plugins"
    (lib.mapAttrsToList (name: path: { inherit name path; }) cfg.extraPlugins);

  # The password plugin is on exactly when a password is set here.
  passwordPlugin =
    if cfg.password != null then { password = cfg.password; }
    else if cfg.passwordFile != null then { password_file = toString cfg.passwordFile; }
    else { enabled = false; };

  noNulls = lib.filterAttrsRecursive (_: v: v != null);

  settings = noNulls ({
    flake            = cfg.flake;
    config_dir       = cfg.configDir;
    exclude          = cfg.exclude;
    default_file     = cfg.defaultFile;
    state_dir        = stateDir;
    listen           = cfg.listen;
    interface        = cfg.interface;
    port             = cfg.port;
    # The address itself, when it is one in particular: the certificate is made for it (see
    # generateCa), so it is a name the browser will use. Without it a save is refused (403).
    hosts            = cfg.hosts ++ cfg.certNames
                       ++ lib.optional (!isLocal && !builtins.elem cfg.listen [ "0.0.0.0" "::" ]) cfg.listen;
    users            = cfg.users;
    session.cookies  = {
      days  = cfg.session.cookies.days;
      renew = if cfg.session.cookies.renew then true else null;
    };
    theme            = cfg.theme;
    themes_dir       = if cfg.themes != { } then "${themesDir}" else null;
    plugins_dir      = if cfg.extraPlugins != { } then "${pluginsDir}" else null;
    sections         = cfg.sections;
    mode             = cfg.mode;
    backups          = cfg.backups;
    terminal         = cfg.terminal;
    terminal_script  = "${packages.eznix-terminal}/share/eznix-terminal/eznix-terminal.py";
    terminal_auto_hide = cfg.terminalAutoHide;
    cert             = if cfg.generateCert then "${certDir}/localhost.pem" else cfg.cert;
    key              = if cfg.generateCert then "${certDir}/localhost-key.pem" else cfg.key;
    ca               = if cfg.generateCert then "${certDir}/ca.pem" else null;
    buttons          = map noNulls cfg.buttons;
    plugin           = lib.recursiveUpdate { password = passwordPlugin; } cfg.plugins;
    # dir and shell go to the terminal process as arguments too, and the page compares the two
    # (a terminal started with other settings than these is offered a restart).
    terminals        = lib.optionalAttrs cfg.terminal (lib.mapAttrs (_: t: noNulls {
      inherit (t) port key_file;
      dir   = cfg.flake;
      shell = cfg.shell;
    }) terminals);
  } // extra);

  # Where a generated certificate lives. Needs a state folder the module knows the path of.
  certDir = stateDir;
in
{
  inherit isLocal certDir;

  toml = (pkgs.formats.toml { }).generate "eznix.toml" settings;

  # Arguments for a terminal the module runs, matching the [terminals.NAME] table above.
  terminalArgs = t: lib.escapeShellArgs ([ "--port" (toString t.port) "--key-file" t.key_file "--dir" cfg.flake ]
    ++ lib.optionals (cfg.shell != null) [ "--shell" cfg.shell ]);

  # `eznix --generate-ca`: a no-op when the certificate exists and still carries these names.
  generateCa = eznix: lib.optionalString cfg.generateCert ''
    ${eznix} --generate-ca ${lib.escapeShellArg certDir} ${lib.concatMapStringsSep " " (n: "--san ${lib.escapeShellArg n}")
      (lib.optional (!isLocal && !builtins.elem cfg.listen [ "0.0.0.0" "::" ]) cfg.listen ++ cfg.certNames)}
  '';

  # trustCert: make this user's browsers trust the generated authority. Run as that user, never
  # as root: it writes into their own certificate databases, which is all it needs.
  #
  # Browsers on Linux don't look at the system's certificates. Chrome, Chromium and Brave read
  # ~/.pki/nssdb; Firefox reads neither and keeps a database of its own in every profile, on
  # every system (so on macOS, where the others use the keychain, this is still what Firefox
  # needs -- `nssdb = false` there). A Firefox profile that has never been started has no
  # database yet and gets one here, as `mkcert -install` does it.
  #
  # Nothing is rewritten when the authority is already there: this runs at every start of a
  # service, and compares first. certutil prints a certificate with CRLF line ends and the
  # file has LF, hence the tr. Ported from ezconf, where each of these was found the hard way;
  # there it ran as root for a list of users and was on by default.
  trustCertScript = { nssdb ? true, firefoxProfiles }:
    let
      certutil = "${pkgs.coreutils}/bin/timeout 10 ${pkgs.nssTools}/bin/certutil";
      name     = lib.escapeShellArg "eznix local authority";
    in pkgs.writeShellScript "eznix-trust-cert" ''
      ca=${lib.escapeShellArg "${certDir}/ca.pem"}
      [ -f "$ca" ] || exit 0
      trust() {
        if ${certutil} -d "sql:$1" -L -a -n ${name} 2>/dev/null | ${pkgs.coreutils}/bin/tr -d '\r' | ${pkgs.diffutils}/bin/cmp -s - "$ca"; then
          return 0
        fi
        ${certutil} -d "sql:$1" -D -n ${name} 2>/dev/null || true
        ${certutil} -d "sql:$1" -A -t "C,," -n ${name} -i "$ca" \
          || echo "eznix: could not add its certificate authority to $1" >&2
      }
      ${lib.optionalString nssdb ''
        db="$HOME/.pki/nssdb"
        if [ ! -d "$db" ]; then
          ${pkgs.coreutils}/bin/mkdir -p "$db"
          ${certutil} -d "sql:$db" -N --empty-password 2>/dev/null || true
        fi
        trust "$db"
      ''}
      for profile in ${firefoxProfiles}; do
        [ -d "$profile" ] || continue      # a pattern that matched nothing stays as it is
        profile="''${profile%/}"
        if [ ! -f "$profile/cert9.db" ]; then
          ${certutil} -d "sql:$profile" -N --empty-password 2>/dev/null || true
        fi
        trust "$profile"
      done
      exit 0
    '';

  # The eznix-autocomplete command put on PATH: the generator, already told this install's flake
  # and where the editor reads suggestions from. `out` is a shell expression (it may use $HOME).
  autocompleteCommand = out: pkgs.writeShellScriptBin "eznix-autocomplete" ''
    exec ${packages.eznix-autocomplete}/bin/eznix-autocomplete --flake ${lib.escapeShellArg cfg.flake} --output "${out}" "$@"
  '';

  # The folder of *.json files. Nothing is put in it: what turns the files into configuration
  # is `eznix.lib.jsonDir`, imported by the flake (see json2nix.nix for what it replaced).
  configDirScript = ''
    mkdir -p ${lib.escapeShellArg cfg.configDir}
  '';

  assertions = [
    {
      assertion = !cfg.trustCert || cfg.generateCert;
      message   = "services.eznix.trustCert is for the certificate eznix makes itself: it needs generateCert (on by default when listen isn't this machine; set it for HTTPS on localhost).";
    }
    {
      # Refused here, at the rebuild, and not found out in the browser: a certificate for the
      # wrong name and saves that fail. (hosts counts too: behind a proxy the names go there.)
      # (listen is "0.0.0.0" by default once interface is set; with an address of its own
      # there is a name to go by, interface or not.)
      assertion = !(builtins.elem cfg.listen [ "0.0.0.0" "::" ])
                  || cfg.certNames != [ ] || cfg.hosts != [ ];
      message   = "services.eznix.certNames is empty. Listening on every address (listen = \"0.0.0.0\", also what interface alone gives), eznix cannot know what you will type in the browser: list the host name or address you open it by, for example certNames = [ \"192.168.1.2\" ], or set listen to that address.";
    }
    {
      assertion = !(cfg.session.cookies.renew && cfg.session.cookies.days == null);
      message   = "services.eznix.session.cookies.renew needs days: a login that lasts until the browser is closed has no days to count again.";
    }
    {
      # What the templates (flake.nix, `templates`) put where the user's name goes. Left in, the
      # system builds and then nobody can log in, so say it here. On macOS `users` defaults to
      # the primary user, which covers the placeholder there too.
      assertion = !builtins.elem "YOUR-USER-NAME" cfg.users;
      message   = "services.eznix: YOUR-USER-NAME is still in the JSON file the template made. Replace it with your user name.";
    }
    {
      assertion = (cfg.cert == null) == (cfg.key == null);
      message   = "services.eznix: cert and key go together.";
    }
    {
      assertion = !(cfg.generateCert && cfg.cert != null);
      message   = "services.eznix: set either generateCert or cert/key, not both.";
    }
    {
      assertion = !(cfg.generateCert && stateDir == null);
      message   = "services.eznix.generateCert needs a state folder with a known path.";
    }
  ];

  options = {
    enable = mkEnableOption "eznix, a web-based Nix configuration editor";

    flake = mkOption {
      type        = types.str;
      default     = defaults.flake;
      description = "The flake eznix edits: where the terminal starts, what the suggestions are generated from, and what a system export zips up. On macOS and with home-manager, where eznix runs as one person, this and configDir may start with `~/` for their home folder.";
    };
    configDir = mkOption {
      type        = types.str;
      default     = "${cfg.flake}/eznix";
      defaultText = lib.literalExpression ''"''${flake}/eznix"'';
      description = "The folder of *.json files eznix edits, each one a tab. It starts empty. Import it from your configuration with `imports = [ (inputs.eznix.lib.jsonDir ./eznix) ];`, which merges every file in it.";
    };
    exclude = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      example     = [ "package.json" "vendor" ];
      description = "Paths in configDir, relative to it, that are not configuration: a file, or a folder with everything under it. The editor leaves them alone. Give `lib.jsonDir` the same list (`{ dir = ./eznix; exclude = [ ... ]; }`), which is what keeps them out of the configuration; a module cannot do that for you.";
    };
    defaultFile = mkOption {
      type        = types.str;
      default     = "configuration.json";
      description = "The file to open first, in a browser that hasn't picked one before. Only a hint; nothing creates it.";
    };

    listen = mkOption {
      type        = types.str;
      default     = if cfg.interface != null then "0.0.0.0" else "127.0.0.1";
      defaultText = lib.literalExpression ''if interface != null then "0.0.0.0" else "127.0.0.1"'';
      description = "Address to listen on. Anything other than this machine itself turns generateCert on by default. With \"0.0.0.0\" (every address) eznix cannot know what you will type in the browser, so put that host name or address in certNames: without it the certificate does not match what the browser asked for, and saving is refused.";
    };
    interface = mkOption {
      type        = types.nullOr types.str;
      default     = null;
      example     = "wg0";
      description = "A network interface, by name, that eznix is reached through and no other; it then listens on every address of it, also when that address changes. This machine itself is not let in either, unless it is the loopback interface that is named. Set listen to this machine's address on that interface as well, or put the host name or address you open it by in certNames: without either the certificate does not match and saving is refused.";
    };
    port = mkOption {
      type        = types.port;
      default     = 9090;
      description = "Port of the editor.";
    };
    terminalPort = mkOption {
      type        = types.port;
      default     = cfg.port + 1;
      defaultText = lib.literalExpression "port + 1";
      description = "First port for the terminals. They listen on 127.0.0.1 only and are reached through the editor's own port; with several users each gets the next one up.";
    };
    hosts = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "Extra host names requests may be addressed to, such as the server_name of a reverse proxy in front of eznix. If that proxy does not pass the browser's Host header on, add the page's address as well (\"https://nix.example.org\"). [ \"*\" ] accepts any.";
    };

    users = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "Who may log in with their system password.";
    };
    session.cookies.days = mkOption {
      type        = types.nullOr (types.numbers.between 0.01 400);
      default     = null;
      example     = 400;
      description = "How many days a login lasts, counted from the login. 400 is the longest a browser keeps a cookie, so there is nothing longer to choose. Left unset, a login lasts until the browser is closed.";
    };
    session.cookies.renew = mkOption {
      type        = types.bool;
      default     = false;
      description = "Count the days from the last time the page was opened, not from the login: someone who opens eznix more often than that is then never logged out. Needs days.";
    };
    password = mkOption {
      type        = types.nullOr types.str;
      default     = null;
      description = "Log in with this password instead of a system password (the password plugin). It ends up readable in the Nix store; use passwordFile for anything that matters.";
    };
    passwordFile = mkOption {
      type        = types.nullOr types.path;
      default     = null;
      description = "A file holding the password to log in with, read when eznix starts.";
    };

    terminal = mkOption {
      type        = types.bool;
      default     = true;
      description = "The terminal panel, with its command buttons.";
    };
    shell = mkOption {
      type        = types.nullOr types.str;
      default     = null;
      description = "Shell the terminal runs. Left unset, each user's own.";
    };
    terminalAutoHide = mkOption {
      type        = types.bool;
      default     = true;
      description = "Hide the open terminal panel on a click anywhere outside it.";
    };
    buttons = mkOption {
      default     = [ ];
      description = "Command buttons in the terminal bar. (Buttons can also be set from the editor itself, in any *.json file, under services.eznix.buttons; those are read straight from the file. A button declared here in Nix shows only with static = true.)";
      example     = lib.literalExpression ''[ { label = "Rebuild"; command = "sudo nixos-rebuild switch"; save_first = true; static = true; } ]'';
      type        = types.listOf (types.submodule {
        options = {
          label       = mkOption { type = types.str; description = "Text on the button."; };
          command     = mkOption { type = types.str; description = "What it types into the terminal."; };
          save_first  = mkOption { type = types.bool; default = false; description = "Unavailable while there are unsaved changes."; };
          clear_first = mkOption { type = types.bool; default = true;  description = "Clear the terminal before running."; };
          menu        = mkOption { type = types.nullOr types.str; default = null; description = "Group buttons of the same menu name into one dropdown; \"A/B\" nests."; };
          mode        = mkOption { type = types.nullOr (types.enum [ "install" ]); default = null; description = "\"install\": shown in the install-mode row."; };
          static      = mkOption { type = types.bool; default = false; description = "Show this button although it is declared in Nix and not in a *.json file."; };
        };
      });
    };

    theme = mkOption {
      # The ones that ship, as choices in the editor, or any other name: one of your own.
      type        = types.either (types.enum [ "nixos" "dark" "gruvbox" "osx" "osx-dark" "osx-light" ]) types.str;
      default     = defaults.theme;
      description = "The theme a browser starts with: nixos, dark, gruvbox, osx-dark, osx-light, osx (light or dark, following the system the browser runs on), or one of your own from themes.";
    };
    themes = mkOption {
      type        = types.attrsOf types.path;
      default     = { };
      example     = lib.literalExpression "{ mine = ./mine.css; }";
      description = "Your own themes, name -> CSS file. See THEMES.md.";
    };
    sections = mkOption {
      type        = types.enum [ "collapsed" "expanded" ];
      default     = "collapsed";
      description = "How foldable sections start out.";
    };
    mode = mkOption {
      type        = types.nullOr (types.enum [ "install" ]);
      default     = null;
      description = "\"install\": show the buttons with mode = \"install\" in their own row and grey out the ordinary ones. For an installer image.";
    };
    backups = mkOption {
      type        = types.ints.unsigned;
      default     = 5;
      description = "How many earlier versions of each file to keep, one made on every save. 0: none.";
    };

    plugins = mkOption {
      type        = types.attrsOf (types.attrsOf types.anything);
      default     = { };
      example     = lib.literalExpression "{ system.backups = 10; documents.enabled = false; }";
      description = "Settings for plugins, by name. enabled = false leaves one out. Shipped: system (export, import and restore of the whole flake), documents (the flake's Markdown files), password (set through password/passwordFile).";
    };
    extraPlugins = mkOption {
      type        = types.attrsOf types.path;
      default     = { };
      example     = lib.literalExpression "{ hello = ./hello; }";
      description = "Your own plugins, name -> folder. A plugin runs with everything eznix itself can do; install only what you would run as a program.";
    };

    generateCert = mkOption {
      type        = types.bool;
      default     = !isLocal && cfg.cert == null;
      defaultText = lib.literalExpression "listen isn't this machine itself, and no cert is set";
      description = "Serve HTTPS with a certificate eznix makes itself, signed by a local authority of its own. Browsers warn until that authority is trusted; the login page offers it for download.";
    };
    trustCert = mkOption {
      type        = types.bool;
      default     = false;
      description = "Make the browsers on this machine trust the generated certificate, so they don't warn: the authority is added to the certificate lists of Chrome, Chromium, Brave and Firefox for the people eznix runs for (on macOS to the keychain, which asks for your password once, at a rebuild typed in a terminal). Only for browsers on this machine; on another computer the authority is added there by hand. A browser that is open may need a restart to notice.";
    };
    certNames = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "The host names and addresses you open eznix by. The generated certificate is made for them, and requests addressed to them are accepted. Needed when listen is \"0.0.0.0\", which it also is with interface set and no listen: eznix then has no way to know them, the certificate names only localhost, the browser complains about it on every other name, and saving is refused. A specific listen address is included by itself.";
    };
    cert = mkOption {
      type        = types.nullOr types.str;
      default     = null;
      description = "Serve HTTPS with this certificate (PEM), with key.";
    };
    key = mkOption {
      type        = types.nullOr types.str;
      default     = null;
      description = "The certificate's private key (PEM).";
    };
  };
}
