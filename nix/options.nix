# What the three modules share: the options, and the eznix.toml made from them.
#
#   packages   nix/packages.nix, evaluated
#   defaults   { flake, theme, themeText ? }: what differs by platform (themeText: how the
#              theme's default is said in the documentation, where it is worked out)
#   stateDir   where this install keeps its state (null: the server's own default, ~/.local/state/eznix)
#   terminals  user -> { port, key_file }: terminals run by the module, one per user
#   extra      more top-level eznix.toml keys from the module (terminal_restart, auth_helper, ...)
#   hostNames  what the machine is called, where the module can know: named in the
#              certificate and accepted in requests without being listed in certNames
#   prog       config.programs.eznix, where the module has it (the application-menu entry)
{ lib, pkgs, cfg, packages, defaults, stateDir, terminals ? { }, extra ? { }, hostNames ? [ ], prog ? null }:
let
  inherit (lib) mkOption mkEnableOption types;

  # Reached from this machine alone: every interface named is the loopback one, or every
  # address is.
  isLocal = (cfg.interfaces != [ ] && lib.all (i: builtins.elem i [ "lo" "lo0" ]) cfg.interfaces)
         || (cfg.listenAddresses != [ ] && lib.all (a: builtins.elem a [ "127.0.0.1" "::1" "localhost" ]) cfg.listenAddresses);
  # The addresses eznix is told to answer on, which the certificate can therefore name.
  # And the machine's own names. Both are what eznix can know of how it will be opened
  # without being told; certNames is for the rest. (The names were left to certNames until
  # 2026-10-12: the user had put config.networking.hostName and fqdn there by hand on the
  # router and asked why eznix did not.)
  listenNames = lib.optionals (!isLocal)
    (lib.unique (lib.filter (a: !builtins.elem a [ "0.0.0.0" "::" ]) cfg.listenAddresses ++ hostNames));

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
    interfaces       = cfg.interfaces;
    listen_addresses = if cfg.listenAddresses == [ ] then null else cfg.listenAddresses;
    port             = cfg.port;
    # The address itself, when it is one in particular: the certificate is made for it (see
    # generateCa), so it is a name the browser will use. Without it every request by that name is refused (403).
    hosts            = cfg.hosts ++ cfg.certNames
                       ++ listenNames;
    trusted_proxies  = cfg.trustedProxies;
    users            = cfg.users;
    session          = {
      days  = cfg.session.days;
      renew = if cfg.session.renew then true else null;
    };
    theme            = cfg.theme;
    themes_dir       = if cfg.themes != { } then "${themesDir}" else null;
    plugins_dir      = if cfg.extraPlugins != { } then "${pluginsDir}" else null;
    collapse_level   = cfg.collapseLevel;
    indent           = cfg.indent;
    arrow_level      = cfg.arrowLevel;
    compact_level    = cfg.compactLevel;
    mode             = cfg.mode;
    backups          = cfg.backups;
    debug            = if cfg.debug then true else null;
    terminal         = cfg.terminal;
    terminal_script  = "${packages.eznix-terminal}/share/eznix-terminal/eznix-terminal.py";
    terminal_auto_hide = cfg.terminalAutoHide;
    cert             = if generateCert then "${certDir}/localhost.pem" else if cfg.enableHttps then cfg.cert else null;
    key              = if generateCert then "${certDir}/localhost-key.pem" else if cfg.enableHttps then cfg.key else null;
    ca               = if generateCert then "${certDir}/ca.pem" else null;
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

  # HTTPS is one switch, enableHttps. With it on and no cert/key given, eznix makes the
  # certificate itself: that used to be an option of its own (generateCert, which enableHttps
  # is the new name of, see the modules' imports), and people had to know that "HTTPS" was
  # spelled "generate a certificate".
  generateCert = cfg.enableHttps && cfg.cert == null;

  # programs.eznix: eznix in the application menu, made from the configuration. The user
  # asked for it on 2026-10-13, after a day of an app installed from the browser going wrong
  # each time HTTPS was switched on or off (see "HTTPS" in CLAUDE.md): that app belongs to
  # the address it was installed from, and this one is told the address at every rebuild.
  #
  # It opens the address in the default browser (xdg-open), an ordinary tab. Until
  # 2026-10-15 it was a Chromium-family browser in app mode (--app=URL, options `browser`
  # and `windowClass`), a window of its own; under Plasma that window had Plasma's title bar
  # and frame, which a page cannot colour, and making it the browser's own was a setting of
  # the browser's profile or a profile of eznix's own. The user chose the plain link.
  #
  # One entry is this machine's own editor (enable, url); `apps` adds one for each other
  # editor named there, so that one desktop has every machine it looks after in its menu
  # (the user, 2026-10-13: "can i add more programs.eznix to other machines?").
  appIcon = pkgs.runCommand "eznix-icon" { } ''
    mkdir -p $out/share/icons/hicolor/scalable/apps
    ${packages.eznix}/bin/eznix --icon ${lib.escapeShellArg cfg.theme} > $out/share/icons/hicolor/scalable/apps/eznix.svg
  '';
  mkApp = { url, label, name }: pkgs.makeDesktopItem {
    inherit name;
    desktopName    = label;
    comment        = "Nix configuration editor";
    icon           = "${appIcon}/share/icons/hicolor/scalable/apps/eznix.svg";
    exec           = "${pkgs.xdg-utils}/bin/xdg-open ${url}";
    categories     = [ "Settings" "System" ];
  };
  # An entry is named for its address, "eznix (https://router.lan:9090)", whichever machine
  # it is: the user's choice on 2026-10-15. It was named for the machine before ("eznix
  # (box)" for this one, "eznix (NAME)" for one of `apps`).
  labelOf = url: "eznix (${lib.removeSuffix "/" url})";
  appEntries =
    lib.optional prog.enable (mkApp { inherit (prog) url; name = "eznix"; label = labelOf prog.url; })
    ++ lib.mapAttrsToList (name: url: mkApp { inherit url; name = "eznix-${name}"; label = labelOf url; }) prog.apps;
  # In the let, so that the generator command below can be given it too.
  toml = (pkgs.formats.toml { }).generate "eznix.toml" settings;
in
{
  inherit isLocal certDir generateCert;

  # The application-menu entries, and the options they are set with (see appIcon above).
  apps = appEntries;
  programOptions = {
    enable = mkEnableOption "eznix in the application menu, with eznix's icon: it opens the address the editor is configured for in the default browser";
    url = mkOption {
      type        = types.str;
      default     = let
          here = cfg.interfaces == [ ] || builtins.elem "lo" cfg.interfaces;
          host = if here && (cfg.listenAddresses == [ ] || builtins.elem "127.0.0.1" cfg.listenAddresses) then "localhost"
                 else if cfg.listenAddresses != [ ] then builtins.head cfg.listenAddresses
                 else if hostNames != [ ] then builtins.head hostNames
                 else "localhost";
        in "http${lib.optionalString cfg.enableHttps "s"}://${host}:${toString cfg.port}/";
      defaultText = lib.literalExpression "the editor of this machine, by its own settings: http or https, localhost or the machine's name, its port";
      example     = "https://router.lan:9090/";
      description = "The address the entry opens. By itself it is this machine's own editor, worked out from services.eznix, so it follows a change of port or of HTTPS at the next rebuild. Set it to have the entry open the editor of another machine.";
    };
    apps = mkOption {
      type        = types.attrsOf types.str;
      default     = { };
      example     = { router = "https://router.lan:9090/"; };
      description = "More entries in the application menu, one for each name: the address of another machine's editor. Each is shown as eznix (ADDRESS); the name tells the entries apart in the configuration. They are there whether or not enable is set, which is the entry for this machine's own editor.";
    };
  };

  inherit toml;

  # Arguments for a terminal the module runs, matching the [terminals.NAME] table above.
  terminalArgs = t: lib.escapeShellArgs ([ "--port" (toString t.port) "--key-file" t.key_file "--dir" cfg.flake ]
    ++ lib.optionals (cfg.shell != null) [ "--shell" cfg.shell ]);

  # `eznix --generate-ca`: a no-op when the certificate exists and still carries these names.
  generateCa = eznix: lib.optionalString generateCert ''
    ${eznix} --generate-ca ${lib.escapeShellArg certDir} ${lib.concatMapStringsSep " " (n: "--san ${lib.escapeShellArg n}")
      (listenNames ++ cfg.certNames)}
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
  # and where the editor reads suggestions from, and given eznix.toml for the plugins that add to
  # them (your own, and which of the shipped ones are on). `out` is a shell expression (it may use $HOME).
  autocompleteCommand = out: pkgs.writeShellScriptBin "eznix-autocomplete" ''
    exec ${packages.eznix-autocomplete}/bin/eznix-autocomplete --flake ${lib.escapeShellArg cfg.flake} --output "${out}" --config ${toml} "$@"
  '';

  # The folder of *.json files. Nothing is put in it: what turns the files into configuration
  # is `eznix.lib.jsonDir`, imported by the flake (see json2nix.nix for what it replaced).
  configDirScript = ''
    mkdir -p ${lib.escapeShellArg cfg.configDir}
  '';

  assertions = [
    {
      assertion = !cfg.trustCert || generateCert;
      message   = "services.eznix.trustCert is for the certificate eznix makes itself: it needs enableHttps, with no cert and key of your own (on by default when eznix is reached from elsewhere; set it for HTTPS on localhost).";
    }
    # (certNames empty while listening on every address was refused here until 2026-10-12,
    # when a save by a plain address stopped needing the address listed: a machine that gets
    # its address from the network had nothing true to put there. What is left of an empty
    # certNames is a certificate that names only localhost, which the descriptions say.)
    {
      assertion = !(cfg.session.renew && cfg.session.days == null);
      message   = "services.eznix.session.renew needs days: a login that ends when the page is closed has no days to count again.";
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
      assertion = cfg.enableHttps || cfg.cert == null;
      message   = "services.eznix: cert and key are set but enableHttps is false, so they would not be used. Remove one or the other.";
    }
    {
      assertion = !(generateCert && stateDir == null);
      message   = "services.eznix.enableHttps without cert and key needs a state folder with a known path, for the certificate eznix makes.";
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
      example     = [ "package.json" "vendor" "*.lock.json" ];
      description = "What in configDir is not configuration, each entry read like a line of a .gitignore: a name leaves out a file or a folder of that name at any depth, with everything under a folder; `/name` or `a/b` only from the top of configDir; `*`, `?`, `[a-z]` and `**` are wildcards; `!entry` takes one back. The editor leaves them alone. Give `lib.jsonDir` the same list (`{ dir = ./eznix; exclude = [ ... ]; }`), which is what keeps them out of the configuration; a module cannot do that for you.";
    };
    defaultFile = mkOption {
      type        = types.str;
      default     = "configuration.json";
      description = "The file to open first, in a browser that hasn't picked one before. Only a hint; nothing creates it.";
    };

    interfaces = mkOption {
      type        = types.listOf types.str;
      # With addresses and nothing said here, those addresses through any interface: tied
      # to lo, an address of the network could not be reached at all.
      default     = if cfg.listenAddresses == [ ] then [ "lo" ] else [ ];
      defaultText = lib.literalExpression ''[ "lo" ], or [ ] when listenAddresses is set'';
      example     = [ "lo" "enp1s0" ];
      description = "The network interfaces eznix is reached through, by name, and no others. \"lo\" is this machine itself, and all there is unless you add to it: [ \"lo\" \"enp1s0\" ] opens eznix here and on that network. Through an interface eznix answers on every address it has, also when that changes (DHCP), so there is no address to set. Meant for this machine and a network you trust: do not list an interface that faces the internet (the router's WAN), since whoever logs in gets a shell. An empty list is every interface, for where their names are not known, and what this is when left unset with listenAddresses set. One that is not there is left out, with a line in the log. Reached from elsewhere, enableHttps is on by default; opened by a host name instead of an address, put that name in certNames.";
    };
    listenAddresses = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      example     = [ "192.168.1.2" ];
      description = "Addresses to answer on, and no others. Set by itself, with interfaces left unset, eznix is reached at these addresses through any interface, and not as localhost unless 127.0.0.1 is one of them. With interfaces set as well, it is these addresses of those interfaces. Empty, the usual: every address of the interfaces. An address given here is in the generated certificate by itself.";
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
      description = "Extra host names requests may be addressed to, such as the server_name of a reverse proxy in front of eznix. If that proxy does not pass the browser's Host header on, add the page's address as well (\"https://nix.example.org\"). [ \"*\" ] accepts any, which also lets in a website that points its own name at this machine; an address needs no entry, and this machine's own name is added by itself.";
    };

    trustedProxies = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      example     = [ "127.0.0.1" ];
      description = "Addresses of reverse proxies in front of eznix. The limit on failed logins is counted per address, and everyone behind a proxy arrives from the proxy's address, so without this one person's failed tries would lock the others out. For a connection from one of these, the client's address is read from the X-Forwarded-For header, which the proxy has to set; from any other connection that header is ignored.";
    };

    users = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "Who may log in with their system password. NixOS and macOS only: with home-manager, log in with passwordFile.";
    };
    session.days = mkOption {
      type        = types.nullOr (types.numbers.between 0.01 400);
      default     = null;
      example     = 30;
      description = "How many days a login lasts, counted from the login, whether the page is open or not. 400 is the longest a browser keeps a cookie, so there is nothing longer to choose. Left unset, a login ends when the page has been closed for 15 minutes (the browser quit, the computer asleep), and a day after logging in at the latest.";
    };
    session.renew = mkOption {
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
      description = "A file holding the password to log in with, read when eznix starts, so the password stays out of the Nix store; a secret from sops-nix or agenix works (`config.sops.secrets.NAME.path`), as long as the user eznix runs as can read it. Give it as a string (\"/home/you/.config/eznix/password\"), not a path inside the flake (./password): a flake is copied into the Nix store whole, where every account on the machine can read it.";
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
          description = mkOption { type = types.nullOr types.str; default = null; description = "What the button does, in your own words: shown when the pointer rests on it, above the command."; };
          save_first  = mkOption { type = types.bool; default = false; description = "Saves any unsaved changes before running the command."; };
          clear_first = mkOption { type = types.bool; default = true;  description = "Clear the terminal before running."; };
          menu        = mkOption { type = types.nullOr types.str; default = null; description = "Group buttons of the same menu name into one dropdown; \"A/B\" nests."; };
          mode        = mkOption { type = types.nullOr (types.enum [ "install" ]); default = null; description = "\"install\": shown in the install-mode row."; };
          static      = mkOption { type = types.bool; default = false; description = "Show this button although it is declared in Nix and not in a *.json file."; };
          separator   = mkOption { type = types.nullOr (types.enum [ "before" "after" "both" ]); default = null; description = "A dividing line beside this button, on the side named: in the bar, or across the list when the button is in a menu. There is never more than one line between two buttons, and none at either end."; };
        };
      });
    };
    menus = mkOption {
      default     = { };
      description = "Settings of a menu of buttons, by the name the buttons give as their menu. Like the buttons, read by the editor straight from the *.json files.";
      example     = lib.literalExpression ''{ Network = { order = 10; separator = "before"; }; }'';
      type        = types.attrsOf (types.submodule {
        options = {
          order     = mkOption { type = types.int; default = 0; description = "Where the menu stands in the bar: lowest first, where plain buttons and menus without a number count as 0. So 10 puts it after them and -10 before them."; };
          separator = mkOption { type = types.nullOr (types.enum [ "before" "after" "both" ]); default = null; description = "A dividing line beside the menu, on the side named."; };
        };
      });
    };
    paths = mkOption {
      default     = { };
      description = "Settings of a tab, by its path in the folder of configuration files as the tabs show it: a folder's name, or a file's path without .json (system, software, system/boot). Like the buttons, read by the editor straight from the *.json files.";
      example     = lib.literalExpression ''{ system = { order = -10; }; "system/boot" = { order = -10; }; }'';
      type        = types.attrsOf (types.submodule {
        options = {
          order = mkOption { type = types.int; default = 0; description = "Where the tab stands in its row, a folder among the folders and a file among the files: lowest first, where a tab without a number counts as 0, and tabs with the same number are by name. So 10 puts it after the others and -10 before them."; };
        };
      });
    };

    theme = mkOption {
      # The ones that ship, as choices in the editor, or any other name: one of your own.
      type        = types.either (types.enum [ "nixos" "gruvbox" "osx" "osx-dark" "osx-light" "breeze" "breeze-dark" "breeze-light" "gnome" "gnome-dark" "gnome-light" ]) types.str;
      default     = defaults.theme;
      defaultText = lib.literalMD (defaults.themeText or ''"${defaults.theme}"'');
      description = "The theme a browser starts with, by default the one of the system eznix runs on where that is known (osx on macOS; on NixOS breeze with Plasma or gnome with GNOME, when it is the only desktop enabled) and nixos otherwise: nixos, gruvbox, osx, breeze or gnome (each of those three light or dark, following the system the browser runs on; osx-dark, osx-light and so on for one of the two regardless), or one of your own from themes.";
    };
    themes = mkOption {
      type        = types.attrsOf types.path;
      default     = { };
      example     = lib.literalExpression "{ mine = ./mine.css; }";
      description = "Your own themes, name -> CSS file. See THEMES.md.";
    };
    collapseLevel = mkOption {
      # 0 is taken as well as null, for "none": the editor itself starts a number it is
      # asked to add at 0, which must not be a value the configuration fails on.
      type        = types.nullOr types.ints.unsigned;
      default     = null;
      example     = 4;
      description = "The level from which sections start out folded in the editor, a top-level section being level 1: with 4, services.openssh.settings is shown and what lies inside it is folded. 1 folds every section. Not set (or 0), nothing is folded.";
    };
    arrowLevel = mkOption {
      type        = types.ints.unsigned;
      default     = 3;
      example     = 1;
      description = "The level from which an open section in the editor has an arrow in front of its name, a top-level section being level 1: 1 gives every section one, 0 none. A folded section always has one.";
    };
    compactLevel = mkOption {
      type        = types.ints.unsigned;
      default     = 3;
      example     = 1;
      description = "The level from which a section in the editor that holds nothing but one sub-section is shown as one with it, under both names (services.nginx.virtualHosts as one heading), a top-level section being level 1: 1 from the top, 0 never.";
    };
    indent = mkOption {
      type        = types.numbers.nonnegative;
      default     = 2;
      example     = 1;
      description = "How far in the editor each level of nesting is indented, in characters.";
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
    debug = mkOption {
      type        = types.bool;
      default     = false;
      description = "Log what is only worth knowing while something is being looked into: every request the editor answers and what took long, in the service's log, and what the page does about its connection, in the browser's console. The log is otherwise only starts, logins and errors.";
    };

    plugins = mkOption {
      type        = types.attrsOf (types.attrsOf types.anything);
      default     = { };
      example     = lib.literalExpression "{ system.backups = 10; documents.enabled = false; }";
      description = "Settings for plugins, by name. enabled = false leaves one out. Shipped: system (export, import and restore of the whole flake), documents (the flake's Markdown files), files (menus of the flake's files by kind, each opened in a program of your choosing in a terminal; one of the Nix files unless set), password (set through password/passwordFile).";
    };
    extraPlugins = mkOption {
      type        = types.attrsOf types.path;
      default     = { };
      example     = lib.literalExpression "{ hello = ./hello; }";
      description = "Your own plugins, name -> folder. A plugin runs with everything eznix itself can do; install only what you would run as a program.";
    };

    enableHttps = mkOption {
      type        = types.bool;
      default     = !isLocal || cfg.cert != null;
      defaultText = lib.literalExpression "reached from elsewhere than this machine itself, or cert is set";
      description = "Serve HTTPS. On by itself when eznix is reached from elsewhere than this machine (interfaces, listenAddresses); set it to have HTTPS on localhost too. With no cert and key given, eznix makes a certificate itself, signed by a local authority of its own: browsers warn until that authority is trusted (trustCert does that for the browsers on this machine; the login page offers it for download for others).";
    };
    trustCert = mkOption {
      type        = types.bool;
      default     = false;
      description = "Make the browsers on this machine trust the generated certificate, so they don't warn: the authority is added to the certificate lists of Chrome, Chromium, Brave and Firefox for the people eznix runs for (on macOS to the keychain, which asks for your password once, at a rebuild typed in a terminal). Only for browsers on this machine; on another computer the authority is added there by hand. A browser that is open may need a restart to notice.";
    };
    certNames = mkOption {
      type        = types.listOf types.str;
      default     = [ ];
      description = "More host names and addresses you open eznix by. The generated certificate is made for them, and requests addressed to them are accepted. For when eznix is reached from elsewhere by something it cannot know by itself: the certificate names localhost, this machine's host name (also with its domain, and as NAME.local) and the addresses in listenAddresses, the browser complains about it on every other name or address, and eznix answers nothing but a refusal by a host name that is not listed (by a plain address it answers), which keeps out a website that points its own name at this machine.";
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
