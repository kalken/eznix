"""Autocomplete source: home-manager's options, as home-manager.users.<name>.*.

Run by eznix-autocomplete (see "Plugins" in bin/eznix-autocomplete.py): generate(ctx) returns
what to add to the suggestions. For a NixOS or nix-darwin configuration; a standalone
home-manager configuration's own options already are home-manager's, at the top level."""

SYSTEMS = ("nixos", "darwin")
OPTIONS = True          # what it returns goes into options.json


def generate(ctx):
    """Home-manager options for whichever host is being generated, with no flake changes and no
    username required. `home-manager.users.<name>` (the nested-NixOS-module form) can't be walked
    generically by lib.optionAttrSetToDocList: its submodule type needs a concrete instance name
    to build (home-manager wires `home.username = mkDefault name;` etc. off it), so the generic
    doc-list probe has nothing to hand it. Rather than require a real homeConfigurations.<user>
    output (which forces picking one specific username up front, purely to satisfy that probe),
    this builds a *throwaway* home-manager evaluation directly — home-manager.lib.homeManagerConfiguration
    with an empty module list, reusing the host's own already-built `pkgs` (so no separate system
    string needs guessing) — and reads *its* .options. An option's description/type/default never
    depend on which username it'll eventually be set under, so a placeholder instance name is
    exactly as accurate as a real one for this purpose, and this needs nothing from the consuming
    flake beyond a home-manager input (found by the function it has, whatever it is called). Every path comes back home-manager-root-relative (e.g. "home.packages"); rewritten to
    home-manager.users.<name>.home.packages using the same literal `<name>` wildcard segment the
    frontend already matches generically (WILDCARDS in index.html — the same mechanism behind
    e.g. users.users.<name>), so it applies to whatever real username ends up in a config.
    A flake with no home-manager input at all adds nothing (resolved inside the
    same expression, not a separate probe, so the check costs one attribute lookup already-
    evaluated `target` has to do anyway). It said nothing at all until 2026-10-17, then said so on
    every run; now it says so when asked for by name or with -v (ctx.note()), the user finding
    a line about what a flake does not have more noise than help.
    """
    expr = f"""
let
    target = builtins.getFlake "path:{ctx.target}";
    cfg = target.{ctx.config_attr}."{ctx.host}";
    # The input called home-manager, else any input that has home-manager's function: a flake
    # may name it as it likes (home-manager-unstable, hm), and nothing here depends on the name.
    hmInput = target.inputs.home-manager or (
        let found = builtins.filter (i: (i.lib or {{}}) ? homeManagerConfiguration) (builtins.attrValues target.inputs);
        in if found == [] then null else builtins.head found);
in if hmInput == null then [] else
let
    lib = target.inputs.nixpkgs.lib;
    homeCfg = hmInput.lib.homeManagerConfiguration {{
        pkgs = cfg.pkgs;
        # A throwaway identity, not a real user: home-manager's own base modules (e.g.
        # misc/nixpkgs.nix) force config.home.stateVersion while resolving _module.args.pkgs for
        # every bundled module, including ones nothing enables — needed just to merge the option
        # *declarations* at all, before any per-option safeGet below even runs. None of these
        # three have a default (home-manager requires them explicitly, by design), so an empty
        # modules list can't get past that. An option's description/type/default never depends on
        # any of these three values, so their exact content doesn't matter, only that they exist.
        modules = [ {{
            home.username = "eznix";
            home.homeDirectory = (if cfg.pkgs.stdenv.hostPlatform.isDarwin then "/Users" else "/home") + "/eznix";
            home.stateVersion = lib.trivial.release;
        }} ];
    }};
    opts = homeCfg.options;
    unwrapValue = v:
        if builtins.isAttrs v && builtins.elem (v._type or "") [ "literalExpression" "literalMD" "literalDocBook" ]
        then v.text
        else v;
    safeGet = f: opt:
        let v = unwrapValue (f opt);
            result = builtins.tryEval (builtins.deepSeq v v);
        in if result.success then result.value else null;
    # The same as for the system's options below: no internal ones, and none hidden (removed).
    rawList = builtins.filter (opt: !(opt.internal or false) && (opt.visible or true)) (lib.optionAttrSetToDocList opts);
in map (opt: {{
    path = "home-manager.users.<name>." + opt.name;
    description = safeGet (o: o.description or null) opt;
    type = safeGet (o: o.type or null) opt;
    default = safeGet (o: o.default or null) opt;
    example = safeGet (o: o.example or null) opt;
    required = safeGet (o: !(o ? default) && !(o.internal or false) && (o.visible or true) && !(o.readOnly or false)) opt;
}}) rawList
"""
    result = ctx.nix_eval(["--impure", "--expr", expr])
    if result is None:
        ctx.warn("failed to evaluate home-manager options — skipping (rerun with -v for details, "
             "e.g. a home-manager input incompatible with this nixpkgs version would fail here)")
        return None
    if not result:
        ctx.note("home-manager: the flake has no home-manager input, so there are no "
                 "home-manager.users.<name> options to add")
        return None
    ctx.info(f"  {len(result)} home-manager options (home-manager.users.<name>.*)")
    # The set they all lie in. The system's own options have it only when its home-manager
    # module is imported (the generator keeps one entry per path), and without it nothing here
    # is found by typing: the editor offers an option that has no placeholder before its last
    # part, and every one of these has `<name>` in the middle. The user's ezberry (a flake
    # with the input and not the module) showed nothing for "home" (2026-10-17).
    result.append({
        "path": "home-manager.users",
        "description": "Per-user Home Manager configuration.\n",
        "type": "attribute set of (Home Manager module)",
        "default": {}, "example": None, "required": False,
    })
    return {"options": result}
