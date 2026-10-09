#!/usr/bin/env python3
"""Generate options.json, packages.json, and kernels.json from a NixOS or nix-darwin flake."""

import argparse
import getpass
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
NC     = "\033[0m"

def info(msg):  print(f"{GREEN}{msg}{NC}", file=sys.stderr)
def warn(msg):  print(f"{YELLOW}Warning: {msg}{NC}", file=sys.stderr)
def error(msg): print(f"{RED}Error: {msg}{NC}", file=sys.stderr); sys.exit(1)


VERBOSE = False
OUTPUT_DIR = "."

IS_DARWIN = sys.platform == "darwin"
DEFAULT_TARGET = "/etc/nix-darwin" if IS_DARWIN else "/etc/nixos"

# The flake output the hosts live under, by --type. Everything below reads the same things from
# either one (.options, .pkgs) -- nix-darwin's darwinSystem returns the same shape nixosSystem
# does -- so which one is in use is just this name.
CONFIG_ATTRS = {"nixos": "nixosConfigurations", "darwin": "darwinConfigurations",
                "home": "homeConfigurations"}
CONFIG_ATTR = "nixosConfigurations"

NIX_EVAL_TIMEOUT = 600  # seconds — a third-party module's option defaults can trigger an
                        # import-from-derivation build or a slow fetch; this bounds how long any
                        # one nix eval call (across get_hosts/packages/kernels/options) can hang.

FAILED = []   # the files a run could not produce; see failed()

def failed(name, why):
    """An evaluation failed outright: say so and leave the file from the last good run alone.
    Writing an empty list in its place would wipe every suggestion of that kind from the editor
    -- which picks up whatever is on disk -- over what is often a passing mistake in the
    configuration. The run as a whole then exits with an error."""
    FAILED.append(name)
    print(f"{RED}Failed: {why} — {name} left as it was (rerun with -v for details){NC}", file=sys.stderr)


def write_json(name, data):
    """Written beside the old file and moved over it. Replacing only takes the right to write to
    the folder, where overwriting takes the right to write to the file -- and the last run may
    have been someone else's (the service at first start, another user's terminal after that)."""
    path = Path(OUTPUT_DIR, name)
    tmp = path.with_name(f".{name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o664)
    os.replace(tmp, path)


def nix_eval(args_list, extra_env=None):
    """Run `nix eval --json <args_list>` and return parsed JSON, or None on failure/timeout."""
    env = {**os.environ, **(extra_env or {})}
    # --no-allow-import-from-derivation: we only ever want declarative metadata (types,
    # descriptions, defaults, examples) here, never an actual build — a module (e.g. disko)
    # whose option defaults read real hardware or trigger an IFD build should fail fast instead
    # of silently building/fetching, which is what was hanging generation on a live ISO with
    # no matching disks/network yet.
    try:
        r = subprocess.run(
            ["nix", "eval", "--json", "--no-allow-import-from-derivation"] + args_list,
            capture_output=True, text=True, env=env, timeout=NIX_EVAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        warn(f"nix eval timed out after {NIX_EVAL_TIMEOUT}s (args: {' '.join(args_list)})")
        return None
    if r.returncode != 0:
        if VERBOSE:
            for line in r.stderr.strip().splitlines():
                if not line.startswith(("evaluation warning:", "warning:")):
                    print(f"  {line}", file=sys.stderr)
        return None
    return json.loads(r.stdout)


def get_hosts(target, attr):
    result = nix_eval([f"{target}#{attr}", "--apply", "builtins.attrNames", "--impure"])
    return result or []


def local_hostname():
    """This machine's name as the rebuild tool would look it up in the flake. darwin-rebuild uses
    macOS's LocalHostName, which can differ from what gethostname() returns there (that one can
    follow whatever name the network handed out)."""
    if IS_DARWIN:
        try:
            r = subprocess.run(["scutil", "--get", "LocalHostName"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return socket.gethostname().split(".")[0]


# --- packages ---

EVAL_PKGS_EXPR = r"""
pkgSet:
let
    prefix = builtins.getEnv "PKG_PREFIX";
    mk = n:
        let r = builtins.tryEval (
            let p = pkgSet.${n};
            in if builtins.isAttrs p && (p.type or "") == "derivation"
                  && p ? meta && builtins.isAttrs p.meta && p.meta ? description
               then
                   let desc = p.meta.description;
                   in builtins.seq desc
                       { name = if prefix == "" then n else prefix + "." + n; description = desc; }
               else null
        );
        in if r.success then r.value else null;
in builtins.filter (x: x != null) (map mk
    (builtins.filter (n: n != "") (builtins.attrNames pkgSet)))
"""

DETECT_SETS_EXPR = r"""
pkgs:
let
    isDrv = v: builtins.isAttrs v && (v.type or "") == "derivation";
    isPkgSet = name:
        builtins.any (suffix:
            let l = builtins.stringLength name;
                sl = builtins.stringLength suffix;
            in l > sl && builtins.substring (l - sl) sl name == suffix
        ) [ "Packages" "Plugins" "Gems" "Extensions" ];
    excludeStr = builtins.getEnv "EXCLUDE_PKG_SETS";
    excluded = builtins.filter (s: builtins.isString s && s != "") (builtins.split "[ ,]+" excludeStr);
in builtins.filter (n:
    let r = builtins.tryEval (
        !(builtins.elem n excluded) &&
        isPkgSet n && builtins.isAttrs pkgs.${n} && !(isDrv pkgs.${n})
    );
    in r.success && r.value
) (builtins.filter (n: n != "") (builtins.attrNames pkgs))
"""

def generate_packages(flake_ref, include=None, exclude=None, no_nested=True):
    info("Generating packages.json...")
    packages = {}

    def eval_set(installable, prefix=""):
        return nix_eval([installable, "--apply", EVAL_PKGS_EXPR],
                        extra_env={"PKG_PREFIX": prefix})

    info("  Evaluating top-level packages...")
    top = eval_set(f"{flake_ref}.pkgs")
    if top is None:
        failed("packages.json", "the top-level packages could not be evaluated")
        return
    for p in top:
        packages[p["name"]] = p

    if not no_nested:
        if include:
            set_names = [s.strip() for s in include.replace(",", " ").split() if s.strip()]
        else:
            info("  Detecting nested package sets...")
            set_names = nix_eval(
                [f"{flake_ref}.pkgs", "--apply", DETECT_SETS_EXPR],
                extra_env={"EXCLUDE_PKG_SETS": exclude or ""},
            )
            if set_names is None:
                warn("failed to detect nested package sets — none will be included (rerun with -v for details)")
                set_names = []

        for name in set_names:
            info(f"  Evaluating {name}...")
            result = eval_set(f"{flake_ref}.pkgs.{name}", prefix=name)
            if result is not None:
                for p in result:
                    packages.setdefault(p["name"], p)
            else:
                warn(f"skipped {name} (evaluation failed)")

    out = list(packages.values())
    write_json("packages.json", out)
    info(f"  {len(out)} packages")


# --- kernels ---

KERNELS_EXPR = r"""
pkgs:
let
    names = builtins.filter
        (n: builtins.substring 0 13 n == "linuxPackages")
        (builtins.attrNames pkgs);
    safeGet = name:
        let r = builtins.tryEval (
            let p = pkgs.${name}; in
            if p ? kernel
            then { name = name; description = p.kernel.meta.description or null; }
            else null
        );
        in if r.success then r.value else null;
in builtins.filter (x: x != null) (map safeGet names)
"""

def generate_kernels(flake_ref):
    info("Generating kernels.json...")
    result = nix_eval([f"{flake_ref}.pkgs", "--apply", KERNELS_EXPR])
    if result is None:
        failed("kernels.json", "the kernels could not be evaluated")
        return
    write_json("kernels.json", result)
    info(f"  {len(result)} kernels")


# --- homebrew ---

def _brew_command():
    """How to invoke brew, or None when it isn't installed. Homebrew refuses to run as root, which
    is what this runs as under eznix's own service -- there it's called as whoever owns the
    Homebrew installation instead."""
    brew = shutil.which("brew") or next(
        (p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(p)), None)
    if not brew:
        return None
    if os.geteuid() != 0:
        return [brew]
    try:
        owner = pwd.getpwuid(os.stat(os.path.realpath(brew)).st_uid).pw_name
    except (OSError, KeyError):
        return None
    if owner == "root":
        return None
    return ["sudo", "-H", "-u", owner, "--", brew]


def _brew(brew, args):
    """Run one brew command; its stdout, or None on any failure."""
    env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1"}
    try:
        r = subprocess.run(brew + args, capture_output=True, text=True, env=env, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        warn(f"brew {' '.join(args)}: {e}")
        return None
    if r.returncode != 0:
        if VERBOSE:
            for line in r.stderr.strip().splitlines():
                print(f"  {line}", file=sys.stderr)
        return None
    return r.stdout


def generate_homebrew(flake_ref):
    """brews.json / casks.json: the names homebrew.brews and homebrew.casks can be filled in from.
    Everything comes from the local brew -- its own lists for the core formulas and casks, plus
    what each tap named in the configuration's homebrew.taps provides (asked for tap by tap:
    brew leaves a tap it doesn't consider trusted out of its combined list). A tap's entries are
    written as tap/name, the form that's unambiguous in a Brewfile. Only an installed tap can be
    listed, so one that was just added to the configuration shows up after the next rebuild.

    Writes nothing at all without a working brew, leaving whatever was generated before."""
    brew = _brew_command()
    if not brew:
        info("Homebrew not found — skipping brews.json/casks.json")
        return []
    info("Generating brews.json and casks.json...")
    formulae = _brew(brew, ["formulae"])
    casks = _brew(brew, ["casks"])
    if not formulae or casks is None:
        warn("could not list Homebrew formulas/casks — leaving brews.json/casks.json as they were "
             "(rerun with -v for details)")
        return []
    brews = set(formulae.split())
    casks = set(casks.split())

    taps = nix_eval([f"{flake_ref}.config.homebrew.taps", "--apply", "map (t: t.name or t)"])
    if taps:
        out = _brew(brew, ["tap-info", "--json"] + taps)
        try:
            tap_info = json.loads(out) if out else []
        except ValueError:
            tap_info = []
        for t in tap_info:
            if not t.get("installed"):
                info(f"  tap {t.get('name')} is not installed yet — its formulas appear after a rebuild")
                continue
            brews.update(t.get("formula_names") or [])
            casks.update(t.get("cask_tokens") or [])

    write_json("brews.json", sorted(brews))
    write_json("casks.json", sorted(casks))
    info(f"  {len(brews)} formulas, {len(casks)} casks")
    return ["brews.json", "casks.json"]


# --- home-manager options ---

def generate_home_options(target, host):
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
    flake beyond a `home-manager` input (the standard input name — this doesn't try alternate
    names). Every path comes back home-manager-root-relative (e.g. "home.packages"); rewritten to
    home-manager.users.<name>.home.packages using the same literal `<name>` wildcard segment the
    frontend already matches generically (WILDCARDS in index.html — the same mechanism behind
    e.g. users.users.<name>), so it applies to whatever real username ends up in a config.
    A flake with no `home-manager` input at all (the common case) is a silent, expected no-op —
    resolved with one cheap `or null` inside the same expression, not a separate probe, so the
    common case costs nothing beyond one more attribute lookup already-evaluated `target` has to
    do anyway."""
    expr = f"""
let
    target = builtins.getFlake "path:{target}";
    cfg = target.{CONFIG_ATTR}."{host}";
    hmInput = target.inputs.home-manager or null;
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
    rawList = builtins.filter (opt: !(opt.internal or false)) (lib.optionAttrSetToDocList opts);
in map (opt: {{
    path = "home-manager.users.<name>." + opt.name;
    description = safeGet (o: o.description or null) opt;
    type = safeGet (o: o.type or null) opt;
    default = safeGet (o: o.default or null) opt;
    example = safeGet (o: o.example or null) opt;
    required = safeGet (o: !(o ? default) && !(o.internal or false) && (o.visible or true) && !(o.readOnly or false)) opt;
}}) rawList
"""
    result = nix_eval(["--impure", "--expr", expr])
    if result is None:
        warn("failed to evaluate home-manager options — skipping (rerun with -v for details, "
             "e.g. a home-manager input incompatible with this nixpkgs version would fail here)")
        return []
    if result:
        info(f"  {len(result)} home-manager options (home-manager.users.<name>.*)")
    return result


# --- options ---

def generate_options(target, host):
    info("Generating options.json...")
    expr = f"""
let
    target = builtins.getFlake "path:{target}";
    cfg = target.{CONFIG_ATTR}."{host}";
    opts = cfg.options;
    lib = target.inputs.nixpkgs.lib;
    unwrapValue = v:
        if builtins.isAttrs v && builtins.elem (v._type or "") [ "literalExpression" "literalMD" "literalDocBook" ]
        then v.text
        else v;
    safeGet = f: opt:
        let v = unwrapValue (f opt);
            result = builtins.tryEval (builtins.deepSeq v v);
        in if result.success then result.value else null;
    # internal = true means "implementation detail, not meant to be set directly" (the
    # convention behind e.g. disko's underscore-prefixed options) — drop these before forcing
    # anything else about them, both because they shouldn't be surfaced to users at all, and
    # because it means never having to force a broken internal-only default in the first place.
    rawList = builtins.filter (opt: !(opt.internal or false)) (lib.optionAttrSetToDocList opts);
in map (opt: {{
    path = opt.name;
    description = safeGet (o: o.description or null) opt;
    type = safeGet (o: o.type or null) opt;
    default = safeGet (o: o.default or null) opt;
    example = safeGet (o: o.example or null) opt;
    required = safeGet (o: !(o ? default) && !(o.internal or false) && (o.visible or true) && !(o.readOnly or false)) opt;
}}) rawList
"""
    result = nix_eval(["--impure", "--expr", expr])
    if result is None:
        failed("options.json", "the options could not be evaluated (a missing "
               "hardware-configuration.nix import would fail here, for one)")
        return

    # (A standalone home-manager configuration's own options already *are* home-manager's, at
    # the top level; there is no system they would be nested under.)
    if CONFIG_ATTR != "homeConfigurations":
        result += generate_home_options(target, host)

    # Clear required on options whose description says they are alternatives to another option.
    # NixOS has no formal "mutually exclusive" metadata; the only signal is prose like
    # "Can be used instead of <foo>" or "Use this instead of <bar>".
    _ALT_RE = re.compile(
        r'\b(can be used instead of|use(?:d)? instead of|alternative(?:ly)? (?:to|for)|'
        r'mutually exclusive)\b',
        re.IGNORECASE,
    )
    for opt in result:
        if opt.get('required') and _ALT_RE.search(opt.get('description') or ''):
            opt['required'] = False
    write_json("options.json", result)
    info(f"  {len(result)} options")


# --- summary ---

def print_summary(files):
    print()
    for f in files:
        p = Path(f)
        if p.exists():
            size  = p.stat().st_size
            count = len(json.loads(p.read_text()))
            kb    = size / 1024
            size_str = f"{kb:.0f}K" if kb < 1024 else f"{kb/1024:.1f}M"
            print(f"{f}: {count} entries ({size_str})")


# --- main ---

def main():

    parser = argparse.ArgumentParser(
        prog="eznix-autocomplete",
        description="Generate eznix's autocomplete data (options, packages, kernels, Homebrew\n"
                    "names) from a NixOS, nix-darwin or home-manager flake",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command", nargs="?", default="all",
        choices=["options", "packages", "kernels", "homebrew", "all"],
        help="What to generate (default: all)",
    )
    parser.add_argument("hostname", nargs="?", default="",
                        help="Configuration host name")
    parser.add_argument("-t", "--type", choices=["auto", "nixos", "darwin", "home"], default="auto",
                        help=("Which of the flake's outputs to read: nixosConfigurations,\n"
                              "darwinConfigurations or homeConfigurations (standalone\n"
                              "home-manager). auto (default) tries the system kind matching this\n"
                              "machine first, then the other, then home"))
    parser.add_argument("-e", "--exclude",
                        help="Nested package sets to skip (comma/space separated)")
    parser.add_argument("-i", "--include",
                        help=(
                            "Only include these nested sets (comma/space separated)\n"
                            "Known sets: gnomeExtensions vimPlugins emacsPackages\n"
                            "            haskellPackages nodePackages nodePackages_latest\n"
                            "            python3Packages perlPackages rubyPackages\n"
                            "            ocamlPackages phpPackages rPackages\n"
                            "            luaPackages beamPackages coqPackages\n"
                            "            kdePackages texlivePackages"
                        ))
    parser.add_argument("-f", "--flake", metavar="DIR", default=None,
                        help=f"The flake to read (default: {DEFAULT_TARGET})")
    parser.add_argument("-o", "--output", metavar="DIR", default="webroot/autocomplete",
                        help="Directory to write generated files to (default: webroot/autocomplete/)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show full nix error output for failing evaluations")
    nested = parser.add_mutually_exclusive_group()
    nested.add_argument("--nested",    dest="nested", action="store_true",  default=False,
                        help="Include all auto-detected nested package sets")
    nested.add_argument("--no-nested", dest="nested", action="store_false",
                        help="Top-level packages only (default)")
    args = parser.parse_args()

    global VERBOSE, OUTPUT_DIR, CONFIG_ATTR
    target = args.flake or DEFAULT_TARGET
    VERBOSE = args.verbose
    OUTPUT_DIR = args.output
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # -i implies nested for the listed sets; --nested enables full auto-detection
    no_nested = not args.nested and not args.include

    if not Path(f"{target}/flake.nix").exists():
        error(f"No flake.nix found at {target}")

    # builtins.getFlake "path:..." refuses a path with a symlink anywhere in it ("path '//etc' is a
    # symlink"), and on macOS /etc itself is one (to /private/etc) -- so /etc/nix-darwin, the
    # default there, failed every options evaluation while the package list, which goes through
    # an ordinary flake reference instead, came out fine.
    target = os.path.realpath(target)
    # Everything below reads the flake as a plain folder ("path:"), never as the git repository
    # it may also be: Nix refuses a repository owned by someone else ("not owned by current
    # user"), which is exactly what a root-owned /etc/nixos is to a service that isn't root.
    flake = f"path:{target}"

    info(f"Using flake: {target}")

    # auto: whichever kind this machine itself is comes first, but a flake that only has the other
    # kind is still usable (e.g. editing a NixOS machine's flake from a Mac).
    if args.type == "auto":
        types = (["darwin", "nixos"] if IS_DARWIN else ["nixos", "darwin"]) + ["home"]
    else:
        types = [args.type]
    hosts = []
    for t in types:
        CONFIG_ATTR = CONFIG_ATTRS[t]
        hosts = get_hosts(flake, CONFIG_ATTR)
        if hosts:
            break
    if not hosts:
        error(f"No {' or '.join(CONFIG_ATTRS[t] for t in types)} found")
    info(f"Using {CONFIG_ATTR}. Available hosts: {' '.join(hosts)}")

    host = args.hostname
    if not host:
        # networking.hostName is what actually becomes this machine's runtime hostname, so it's a
        # reliable way to pick the right nixosConfigurations entry without being told explicitly —
        # matters once a flake defines more than one host (e.g. a shared flake for several
        # machines), where picking hosts[0] could silently generate data for the wrong one.
        system_hostname = local_hostname()
        # A standalone home-manager configuration is named for a person, "user" or "user@host",
        # which is also how `home-manager switch` finds the one to use.
        me = getpass.getuser()
        mine = [n for n in (f"{me}@{system_hostname}", me) if n in hosts]
        if CONFIG_ATTR == "homeConfigurations" and mine:
            host = mine[0]
            info(f"Using: {host} (this user)")
        elif system_hostname in hosts:
            host = system_hostname
            info(f"Using: {host} (matches this machine's hostname)")
        else:
            host = hosts[0]
            # Only worth flagging when the pick was actually ambiguous (multiple hosts, one
            # silently chosen) — with a single host there's nothing else it could have been.
            (warn if len(hosts) > 1 else info)(f"Using: {host}")
    elif host not in hosts:
        error(f"Host '{host}' not found. Available: {' '.join(hosts)}")

    info(f"Using host: {host}")
    # Quoted: a home-manager name like "alice@laptop" isn't a plain attribute name.
    flake_ref = f'{flake}#{CONFIG_ATTR}."{host}"'

    generated = []
    if args.command in ("packages", "all"):
        generate_packages(flake_ref, include=args.include, exclude=args.exclude, no_nested=no_nested)
        generated.append("packages.json")
    if args.command in ("options", "all"):
        generate_options(target, host)
        generated.append("options.json")
    # A nix-darwin system has no kernel to choose. Nothing is written for it at all rather than
    # an empty list: eznix.py treats an empty output file as a failed run.
    if CONFIG_ATTR == "darwinConfigurations":
        if args.command == "kernels":
            info("No kernels to list for a nix-darwin configuration")
        if args.command in ("homebrew", "all"):
            generated += generate_homebrew(flake_ref)
    elif CONFIG_ATTR == "homeConfigurations":
        if args.command == "kernels":
            info("No kernels to list for a home-manager configuration")
    elif args.command in ("kernels", "all"):
        generate_kernels(flake_ref)
        generated.append("kernels.json")

    generated = [g for g in generated if g not in FAILED]
    if FAILED:
        print_summary(generated)
        error(f"could not generate {', '.join(FAILED)}")
    info("Done!")
    print_summary(generated)


if __name__ == "__main__":
    main()
