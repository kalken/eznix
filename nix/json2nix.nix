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
}: args @ {
  pkgs,
  lib,
  config,
  ...
}: let
  # What a raw expression ("_expr") can name: everything this module is given. That is `lib`,
  # `config`, `options`, whatever the flake put in `specialArgs` (`inputs`, usually) and
  # `modulesPath` on NixOS, plus `pkgs`, which is only handed to a module that names it, as
  # above. Anything else set through `_module.args` would have to be named there too.
  # `config` is safe here for the reason it is in any module: the names in a file come from
  # the JSON alone and each expression is evaluated only when its value is asked for. The
  # limits are the module system's own: one that reads the option it is part of recurses, a
  # neighbouring name in the same attribute set included (`attrsOf` evaluates every entry to
  # learn which exist). Tried by hand with `nix eval`; checks.json-dir cannot hold an "_expr"
  # (see flake.nix).
  scope = args;

  excludes = map (lib.removeSuffix "/") exclude;
  excluded = relPath: lib.any (e: relPath == e || lib.hasPrefix "${e}/" relPath) excludes;

  # Every *.json file under this directory (including subfolders, for organizing tabs) is an
  # independent config "tab" (edited separately in the UI). No file name is special: what is
  # not configuration is kept out with `exclude`. Dotdirs (e.g. .eznix-backups, when it lives
  # here) are skipped so backup files never get picked up. So is a folder named "X.disabled":
  # one the editor switched off, with everything in it (a file is switched off the same way,
  # "X.json.disabled", which no longer ends in .json). It was ".X.disabled" until 2026-10 and
  # skipped as a dotdir; the user wanted it to stay a visible part of the configuration. They're combined below via lib.mkMerge, so
  # the real NixOS module system performs the merge (list concat, attrset merge, scalar
  # conflict = eval error) — same as splitting configuration.nix across files. Mirrors
  # list_config_files() in bin/eznix.py, `exclude` (_excluded() there) included.
  walk = dir: prefix:
    lib.concatLists (lib.mapAttrsToList (
      name: type: let relPath = prefix + name; in
        if excluded relPath then []
        else if type == "directory"
        then (if lib.hasPrefix "." name || lib.hasSuffix ".disabled" name then [] else walk (dir + "/${name}") "${relPath}/")
        else if type == "regular" && lib.hasSuffix ".json" name
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
        { pkgs, lib, config, ... } @ args: with args; ${val._expr}
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
