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
    default_file     = cfg.defaultFile;
    state_dir        = stateDir;
    listen           = cfg.listen;
    port             = cfg.port;
    hosts            = cfg.hosts ++ cfg.certNames;
    users            = cfg.users;
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

  # The eznix-autocomplete command put on PATH: the generator, already told this install's flake
  # and where the editor reads suggestions from. `out` is a shell expression (it may use $HOME).
  autocompleteCommand = out: pkgs.writeShellScriptBin "eznix-autocomplete" ''
    exec ${packages.eznix-autocomplete}/bin/eznix-autocomplete --flake ${lib.escapeShellArg cfg.flake} --output "${out}" "$@"
  '';

  # The folder of *.json files, and the default.nix in it that turns them into configuration.
  configDirScript = ''
    mkdir -p ${lib.escapeShellArg cfg.configDir}
    cp ${./json2nix.nix} ${lib.escapeShellArg cfg.configDir}/default.nix
    chmod 644 ${lib.escapeShellArg cfg.configDir}/default.nix
  '';

  assertions = [
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
      description = "The flake eznix edits: where the terminal starts, what the suggestions are generated from, and what a system export zips up.";
    };
    configDir = mkOption {
      type        = types.str;
      default     = "${cfg.flake}/eznix";
      defaultText = lib.literalExpression ''"''${flake}/eznix"'';
      description = "The folder of *.json files eznix edits, each one a tab. It starts empty. Import it from your configuration (`imports = [ ./eznix ];`): the default.nix eznix puts there merges every file in it.";
    };
    defaultFile = mkOption {
      type        = types.str;
      default     = "configuration.json";
      description = "The file to open first, in a browser that hasn't picked one before. Only a hint; nothing creates it.";
    };

    listen = mkOption {
      type        = types.str;
      default     = "127.0.0.1";
      description = "Address to listen on. Anything other than this machine itself turns generateCert on by default.";
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
      description = "Extra host names requests may be addressed to, such as the server_name of a reverse proxy in front of eznix. [ \"*\" ] accepts any.";
    };

    users = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "Who may log in with their system password.";
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
      type        = types.str;
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
    certNames = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "Host names and addresses the generated certificate is for, besides localhost and listen.";
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
