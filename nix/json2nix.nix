# A folder of *.json files as one module: `inputs.eznix.lib.jsonDir ./eznix` in `imports`, or
# `inputs.eznix.lib.jsonDir { dir = ./eznix; exclude = [ "notes.json" "vendor" ]; }`.
#
#   dir      the folder eznix edits (`config_dir` there)
#   exclude  paths in it, relative to it, to leave out: a file, or a folder with everything
#            under it. For a folder that holds other JSON than configuration (the flake's own
#            root, say). Give the editor the same list (`exclude`), or it shows them as tabs.
#
# This used to be copied into the folder as its default.nix, so that `imports = [ ./eznix ]`
# worked. As a function nothing has to be installed where the files are, which is what lets
# the folder be one that already has a default.nix of its own.
{
  dir,
  exclude ? [ ],
}: {
  pkgs,
  lib,
  ...
}: let
  scope = {inherit pkgs lib;};

  excludes = map (lib.removeSuffix "/") exclude;
  excluded = relPath: lib.any (e: relPath == e || lib.hasPrefix "${e}/" relPath) excludes;

  # Every *.json file under this directory (including subfolders, for organizing tabs) is an
  # independent config "tab" (edited separately in the UI); custom-options.json is a
  # schema-extension sidecar, not a tab, and dotdirs (e.g. .eznix-backups, when it lives here)
  # are skipped so backup files never get picked up. They're combined below via lib.mkMerge, so
  # the real NixOS module system performs the merge (list concat, attrset merge, scalar
  # conflict = eval error) — same as splitting configuration.nix across files. Mirrors
  # list_config_files() in bin/eznix.py, `exclude` (_excluded() there) included.
  walk = dir: prefix:
    lib.concatLists (lib.mapAttrsToList (
      name: type: let relPath = prefix + name; in
        if excluded relPath then []
        else if type == "directory"
        then (if lib.hasPrefix "." name then [] else walk (dir + "/${name}") "${relPath}/")
        else if type == "regular" && lib.hasSuffix ".json" name && name != "custom-options.json"
        then [relPath]
        else []
    ) (builtins.readDir dir));

  # No folder yet is no files: it can be imported before the first rebuild has made it, and in
  # a git flake an empty folder isn't there at all (git keeps no empty folders).
  jsonFileNames = if builtins.pathExists dir then walk dir "" else [ ];

  resolveExprs = val:
    if builtins.isAttrs val && val ? "_expr"
    then
      import (builtins.toFile "expr.nix" ''
        { pkgs, lib }: ${val._expr}
      '')
      scope
    else if builtins.isList val
    then map resolveExprs val
    else if builtins.isAttrs val
    then
      let active = lib.filterAttrs (_: v: !(builtins.isAttrs v && v ? "_disabled")) val;
      in lib.mapAttrs (_: resolveExprs) active
    else val;

  evaluatedConfigs = map (n: resolveExprs (builtins.fromJSON (builtins.readFile (dir + "/${n}")))) jsonFileNames;
in {
  # What an error names as the place a value was set.
  _file  = "${toString dir} (*.json, edited in eznix)";
  config = lib.mkMerge evaluatedConfigs;
}
