# What `exclude` leaves out, for json2nix.nix: given the list, a function from a path (relative
# to the folder, "a/b.json") to whether an entry matches it. An entry is read as a line of a
# .gitignore, and is made into a regular expression the way _exclude_rule() in bin/eznix.py
# makes one, step for step (what an entry means is written there). The two must agree, since
# one decides what is built and the other what is a tab: change them together.
# test/exclude.json is one table of cases that both are run against (checks.exclude in
# flake.nix, and test/test_server.py).
#
# A name is cut at its wildcards, which become their expressions, and what lies between is
# taken literally; "**" as a whole name is any number of folders. The last entry that matches
# decides. A folder that is left out takes everything under it along: whoever asks has to ask
# about the folders above a path too, or not go into them.
{ lib }: exclude: let
  excludeName = name: lib.concatMapStrings (part:
    if builtins.isList part then (let w = builtins.head part; in
      if w == "*" then "[^/]*"
      else if w == "?" then "[^/]"
      else if lib.hasPrefix "[!" w then "[^" + builtins.substring 2 (-1) w
      else w)
    else lib.escapeRegex part
  ) (builtins.split "(\\*|\\?|\\[[^]]*])" name);
  excludeRule = entry: let
    negated = lib.hasPrefix "!" entry;
    pattern = if negated then lib.removePrefix "!" entry else entry;
    names = builtins.filter (n: n != "") (lib.splitString "/" pattern);
    count = builtins.length names;
    anchored = lib.hasPrefix "/" pattern || count > 1;
    body = lib.concatStrings (lib.imap0 (i: n: let last = i == count - 1; in
      if n == "**" then (if last then ".*" else "(.*/)?")
      else excludeName n + (if last then "" else "/")
    ) names);
  in { inherit negated count; regex = (if anchored then "" else "(.*/)?") + body; };
  excludeRules = builtins.filter (r: r.count > 0) (map excludeRule exclude);
in relPath: lib.foldl' (out: r: if builtins.match r.regex relPath != null then !r.negated else out) false excludeRules
