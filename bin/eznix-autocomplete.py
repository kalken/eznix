#!/usr/bin/env python3
"""Generate options.json, packages.json and choices.json from a NixOS, nix-darwin or home-manager flake.

What every system has is generated here: its options and its packages. What only some have
comes from plugins (see "Plugins" below): the kernels, Homebrew's names, home-manager's options."""

import argparse
import atexit
import getpass
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

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


def mark_running():
    """Leaves `.generating`, holding this process's number, in the output folder for as long as
    this runs. The editor looks for it (_autocomplete_running() in eznix.py) and spins the icon
    of its Autocomplete button meanwhile, wherever the run was started from. Taken away again
    on the way out, also after an error or Ctrl-C; a run that is killed leaves it, which is why
    the editor asks whether that process still exists.

    Made new, never written through what is there: on NixOS the folder is shared by everyone
    in `users`, and a marker written with write_text() followed a link another user had put at
    its name, overwriting and opening up whatever file of this user's it pointed at (found in
    review, 2026-10-18). Whatever is at the name goes first (a link is removed, not followed)."""
    marker = Path(OUTPUT_DIR, ".generating")
    try:
        marker.unlink(missing_ok=True)
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o664)
    except OSError:
        return          # someone else's stale marker we may not replace: only the icon is off
    try:
        os.fchmod(fd, 0o664)
        os.write(fd, f"{os.getpid()}\n".encode())
    finally:
        os.close(fd)
    atexit.register(lambda: marker.unlink(missing_ok=True))


def write_json(name, data):
    """Written beside the old file and moved over it. Replacing only takes the right to write to
    the folder, where overwriting takes the right to write to the file -- and the last run may
    have been someone else's (the service at first start, another user's terminal after that).

    The file beside it is made new under a name nobody can guess (mkstemp): it was named after
    the process number, and in a folder that others write in, a link put at that name ahead of
    time was followed (see mark_running()). The move replaces a link at `name` itself, never
    what it points at."""
    path = Path(OUTPUT_DIR, name)
    fd, tmp = tempfile.mkstemp(dir=OUTPUT_DIR, prefix=f".{name}.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o664)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_choices(entries):
    """choices.json: what an option can be filled in from where its type does not say, by the
    option's path: {"values": [...], "expr": bool, "free": bool}. A value is a text, or
    {"value", "description"}; `expr` says the values are Nix expressions, `free` that they are
    suggestions and anything else may be typed. The editor shows any option listed here as a
    choice and knows none of them by name (choicesFor() in index.html), so a new kind of list
    is a new entry here and nothing there. Entries of other paths are kept: each kind is
    generated by itself and only some exist on a given system."""
    path = Path(OUTPUT_DIR, "choices.json")
    try:
        # Not through a link: another user's link here to a file of this user's would have it
        # read and written out again, readable by everyone in the folder (mark_running()).
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.update(entries)
    write_json("choices.json", data)
    # What the same values were written as until 2026-10-12, a file per kind, read by nothing now.
    for old in ("kernels.json", "brews.json", "casks.json"):
        try:
            Path(OUTPUT_DIR, old).unlink()
        except OSError:
            pass


LAST_ERROR = ""   # what the last failed nix_eval() wrote to stderr; see explain_error()

def explain_error(stderr, flake_dir=""):
    """The cause of a failed evaluation in one line, or None when none is recognised. Nix's own
    text is a long trace, and what most often goes wrong is a file the flake imports that is not
    there (hardware-configuration.nix before it has been generated): that is said by its name
    in the flake, not by its place in the Nix store or on the disk."""
    m = re.search(r"path '([^']+)' does not exist", stderr)
    if m:
        name = re.sub(r"^/nix/store/[a-z0-9]{32}-[^/]+/", "", m.group(1))
        name = name[len(flake_dir) + 1:] if flake_dir and name.startswith(flake_dir + "/") else name
        return f"{name} is missing: a file the flake imports is not there"
    errors = [l.strip() for l in stderr.splitlines() if l.startswith("error:")]
    return errors[-1][len("error:"):].strip() if errors else None


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
        global LAST_ERROR
        LAST_ERROR = r.stderr
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


# --- plugins ---
#
# A source of suggestions that only some systems have is a plugin, the folder eznix loads its
# page and server code from (plugins/NAME/ beside bin/, and plugins_dir of the configuration):
# its plugin.json names a Python file as "autocomplete", and that file holds
#
#     SYSTEMS = ("nixos", "darwin")   # which kinds of configuration it is for; unset: all
#     OPTIONS = True                  # it adds to options.json (default: only to choices.json)
#     def generate(ctx): ...          # returns {"options": [...], "choices": {...}} or None
#
# ctx is a Context: the flake (`target`, `flake_ref`), what was picked (`host`, `kind`,
# `config_attr`), the plugin's own settings (`config`, [plugin.NAME] of the configuration),
# `verbose`, `nix_eval()`, `info()`, `warn()`, `note()` and `failed(file, why)` -- the same ones the
# rest of this file uses, so a plugin prints and fails like the rest. `note()` is for "there is
# nothing for me here" (no home-manager input, no brew): said when the plugin was asked for by
# name or with -v, and silent in an ordinary run, where most plugins have nothing to do. `options` are what
# optionAttrSetToDocList gives here (path, description, type, default, example, required);
# `choices` are written as write_choices() takes them. None says there is nothing to add, and
# `failed()` leaves the file of the last run as it was and ends the run with an error; a plugin
# that only warns lets the rest be written.
#
# It runs when Autocomplete is pressed, as the user who presses it: a plugin is trusted like
# any program, as the server half of one is. [plugin.NAME] enabled = false leaves it out here
# too. Until 2026-10-17 the kernels, Homebrew and home-manager's options were functions in
# this file, each with its own branch in main().

KINDS = {v: k for k, v in CONFIG_ATTRS.items()}     # homeConfigurations -> home


class Context:
    def __init__(self, target, host, flake_ref, config, explicit=False):
        self.target, self.host, self.flake_ref, self.config = target, host, flake_ref, config
        self.config_attr = CONFIG_ATTR
        self.kind = KINDS[CONFIG_ATTR]
        self.verbose = VERBOSE
        self.nix_eval, self.info, self.warn, self.failed = nix_eval, info, warn, failed
        self.note = info if (VERBOSE or explicit) else (lambda msg: None)


def find_plugins(config_file, plugins_dirs):
    """{name: {'module', 'config'}} for every plugin with an "autocomplete" file, from the
    shipped plugins (beside bin/) and the folders given, as the server finds them: a folder
    named like one found before is skipped, and [plugin.NAME] enabled = false leaves one out."""
    cfg = {}
    if config_file:
        if tomllib is None:
            warn("reading a config file needs Python 3.11+ or the tomli package: plugin settings ignored")
        else:
            try:
                with open(config_file, "rb") as f:
                    cfg = tomllib.load(f)
            except (OSError, ValueError) as e:
                warn(f"{config_file}: {e}")
    settings = cfg.get("plugin") if isinstance(cfg.get("plugin"), dict) else {}
    bases = list(plugins_dirs) + ([cfg["plugins_dir"]] if cfg.get("plugins_dir") else [])
    found = {}
    for base in bases:
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            folder = os.path.join(base, name)
            try:
                with open(os.path.join(folder, "plugin.json")) as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                continue
            rel = manifest.get("autocomplete")
            conf = settings.get(name) if isinstance(settings.get(name), dict) else {}
            if (not rel or name in found or conf.get("enabled") is False
                    or manifest.get("name") != name or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name)):
                continue
            path = os.path.realpath(os.path.join(folder, str(rel)))
            if not path.startswith(os.path.realpath(folder) + os.sep) or not os.path.isfile(path):
                warn(f"plugin {name}: no such autocomplete file {rel!r}")
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"eznix_autocomplete_{name.replace('-', '_')}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if not callable(getattr(module, "generate", None)):
                    raise TypeError("no generate(ctx)")
            except Exception as e:
                warn(f"plugin {name} left out: {type(e).__name__}: {e}")
                continue
            found[name] = {"module": module,
                           "config": {k: v for k, v in conf.items() if k != "enabled"}}
    return found


def run_plugin(name, plugin, context_args, explicit=False):
    """What one plugin returns ({'options', 'choices'}, either may be missing), or None when it
    is not for this kind of configuration, has nothing to add, or fails (it is then told to the
    user, and a failed() has marked the run)."""
    module = plugin["module"]
    systems = getattr(module, "SYSTEMS", None)
    ctx = Context(*context_args, plugin["config"], explicit)
    if systems and ctx.kind not in systems:
        return None
    try:
        result = module.generate(ctx)
    except Exception as e:
        warn(f"plugin {name} failed: {type(e).__name__}: {e}")
        return None
    return result if isinstance(result, dict) else None


# --- options ---

def eval_options(target, host):
    """The options of one configuration, as optionAttrSetToDocList gives them, or None when
    they cannot be evaluated."""
    info(f"Evaluating the options of {host}...")
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
    # visible = false is how a removed or renamed option is declared (mkRemovedOptionModule,
    # mkRenamedOptionModule): it is there only to say so when set. Dropped as the NixOS manual
    # drops it (make-options-doc: `opt.visible && !opt.internal`); they were offered as
    # options until 2026-10-15, when the user found programs.eznix.browser still there after
    # its removal.
    rawList = builtins.filter (opt: !(opt.internal or false) && (opt.visible or true)) (lib.optionAttrSetToDocList opts);
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
        why = explain_error(LAST_ERROR, str(target))
        if why:
            print(f"{RED}  {host}: {why}{NC}", file=sys.stderr)
    return result


def pick_options(target, candidates):
    """(host, its options) for the first of `candidates` whose options evaluate, or (None,
    None). The machine's own entry is tried first and the first host after it: an entry that
    does not evaluate here (one whose hardware-configuration.nix is not in the flake, say)
    used to leave no options at all, though the flake's other hosts give the same ones, give
    or take their modules (the user's wish, 2026-10-18)."""
    for n, host in enumerate(candidates):
        result = eval_options(target, host)
        if result is not None:
            return host, result
        if n + 1 < len(candidates):
            warn(f"The options of {host} could not be evaluated; trying {candidates[n + 1]}")
    return None, None


def generate_options(result, extra=()):
    info("Generating options.json...")
    # What plugins add (home-manager's, for one) goes in before the rest is done to all of them,
    # but one entry per path: a plugin may supply what the system has only some of the time.
    known = {o["path"] for o in result}
    result += [o for o in extra if o["path"] not in known]

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
            size     = p.stat().st_size
            count    = len(json.loads(p.read_text()))
            kb       = size / 1024
            size_str = f"{kb:.0f}K" if kb < 1024 else f"{kb/1024:.1f}M"
            print(f"{f}: {count} entries ({size_str})")


# --- main ---

def main():

    parser = argparse.ArgumentParser(
        prog="eznix-autocomplete",
        description="Generate eznix's autocomplete data (options, packages, and what the plugins\n"
                    "add: kernels, Homebrew names, home-manager options) from a NixOS,\n"
                    "nix-darwin or home-manager flake",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command", nargs="?", default="all",
        help="What to generate: options, packages, the name of a plugin, or all (default)",
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
    parser.add_argument("-c", "--config", metavar="FILE", default=None,
                        help="eznix.toml: plugins_dir (your own plugins) and [plugin.NAME] settings,\n"
                             "enabled = false leaving a plugin out")
    parser.add_argument("--plugins-dir", metavar="DIR", action="append", default=[],
                        help="A folder of plugins, one folder each (default: plugins/ beside bin/);\n"
                             "can be given more than once")
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
    mark_running()

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
    candidates = [host]
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
        # Picked here and not named: if its options cannot be evaluated, the first host is
        # tried next (pick_options()). A host named on the command line is the one used.
        candidates = [host] + [h for h in hosts[:1] if h != host]
    elif host not in hosts:
        error(f"Host '{host}' not found. Available: {' '.join(hosts)}")

    plugins = find_plugins(args.config, args.plugins_dir or [os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), "plugins")])
    command = args.command
    if command not in ("options", "packages", "all") and command not in plugins:
        error(f"Unknown command '{command}'. Choose options, packages, all"
              + "".join(f", {n}" for n in plugins))
    # A plugin that adds to options.json is part of making it: asked for by name, that is the
    # options as a whole, not an options.json with only its share in it.
    if command in plugins and getattr(plugins[command]["module"], "OPTIONS", False):
        command = "options"
    wanted = [n for n, p in plugins.items()
              if command == "all" or command == n
              or (command == "options" and getattr(p["module"], "OPTIONS", False))]

    # The options are evaluated first, since they decide the host (pick_options()): the
    # plugins and the packages are then generated from the same one.
    options = None
    if command in ("options", "all"):
        found, options = pick_options(target, candidates)
        if found is None:
            failed("options.json", "the options could not be evaluated")
        else:
            host = found

    info(f"Using host: {host}")
    # Quoted: a home-manager name like "alice@laptop" isn't a plain attribute name.
    flake_ref = f'{flake}#{CONFIG_ATTR}."{host}"'

    # What a plugin returns, by plugin. A name given for what does not apply here (the kernels
    # on a Mac) says so; with `all` it is just left out.
    results = {}
    for name in wanted:
        r = run_plugin(name, plugins[name], (target, host, flake_ref), explicit=args.command == name)
        if r is None and command == name and not FAILED:
            systems = getattr(plugins[name]["module"], "SYSTEMS", None)
            if systems and KINDS[CONFIG_ATTR] not in systems:
                info(f"{name} is for {', '.join(systems)}, not {KINDS[CONFIG_ATTR]}")
        if r:
            results[name] = r

    generated = []
    if command in ("packages", "all"):
        generate_packages(flake_ref, include=args.include, exclude=args.exclude, no_nested=no_nested)
        generated.append("packages.json")
    if options is not None:
        generate_options(options, [o for r in results.values() for o in r.get("options", [])])
    if command in ("options", "all"):
        generated.append("options.json")
    choices = {}
    for r in results.values():
        choices.update(r.get("choices") or {})
    if choices:
        write_choices(choices)
        generated.append("choices.json")

    generated = [g for g in generated if g not in FAILED]
    if FAILED:
        print_summary(generated)
        error(f"could not generate {', '.join(FAILED)}")
    info("Done!")
    print_summary(generated)


if __name__ == "__main__":
    main()
