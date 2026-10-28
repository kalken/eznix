"""Autocomplete source: the names homebrew.brews and homebrew.casks can be filled in from.

Run by eznix-autocomplete (see "Plugins" in bin/eznix-autocomplete.py): generate(ctx) returns
what to add to the suggestions. nix-darwin only, and only with a working brew."""
import glob
import json
import os
import pwd
import shutil
import subprocess
import sys

SYSTEMS = ("darwin",)


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


def _brew(ctx, brew, args):
    """Run one brew command; its stdout, or None on any failure.

    HOMEBREW_FORCE_RUBY_COMMAND: `brew formulae` and `brew casks` are otherwise answered by a
    shell script that prints brew's cached list of names (api/formula_names.txt in its cache
    folder) and nothing at all when that file is not there, with exit status 0. It is not there
    from one brew update until some command next loads the list: on the user's Mac it came and
    went within minutes (2026-10-11), and the editor's list of formulas with it. Brew's own
    command, which that variable asks for and brew's script falls back to itself, loads the
    names and writes the file again. Some seconds slower each."""
    env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1",
           "HOMEBREW_FORCE_RUBY_COMMAND": "1"}
    try:
        r = subprocess.run(brew + args, capture_output=True, text=True, env=env, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        ctx.warn(f"brew {' '.join(args)}: {e}")
        return None
    if r.returncode != 0:
        if ctx.verbose:
            for line in r.stderr.strip().splitlines():
                print(f"  {line}", file=sys.stderr)
        return None
    return r.stdout


def _jws(path):
    """The data of one of brew's signed API files: a JSON object whose `payload` is the JSON
    text of the data itself. None when it can't be read."""
    try:
        with open(path) as f:
            return json.loads(json.load(f)["payload"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _descriptions(ctx, brew):
    """Each formula's and cask's one-line description, {name: desc} for each, from what brew has
    downloaded into its cache: brew itself lists no descriptions short of `brew info --json=v2
    --eval-all`, which reads every package and takes minutes. These files are brew's own and
    not a documented interface: api/internal/packages.TAG.jws.json (both kinds in one, per
    bottle tag; brew 5 and later), else api/formula.jws.json and api/cask.jws.json (a list
    each, before). Whatever cannot be read leaves names without descriptions, nothing worse.
    Only the core formulas and casks are there: a tap's have none."""
    cache = (_brew(ctx, brew, ["--cache"]) or "").strip()
    if not cache:
        return {}, {}
    api = os.path.join(cache, "api")
    newest = sorted(glob.glob(os.path.join(api, "internal", "packages.*.jws.json")),
                    key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    data = _jws(newest[-1]) if newest else None
    if isinstance(data, dict):
        def descs(d):
            return {n: v["desc"] for n, v in (d or {}).items()
                    if isinstance(v, dict) and isinstance(v.get("desc"), str) and v["desc"]}
        return descs(data.get("formulae")), descs(data.get("casks"))

    def listed(name, key):
        items = _jws(os.path.join(api, name))
        return {v[key]: v["desc"] for v in items or []
                if isinstance(v, dict) and isinstance(v.get(key), str)
                and isinstance(v.get("desc"), str) and v["desc"]}
    return listed("formula.jws.json", "name"), listed("cask.jws.json", "token")


def _values(names, descs):
    """choices.json's values: a name, or {value, description} where there is one."""
    return [{"value": n, "description": descs[n]} if n in descs else n for n in sorted(names)]


def generate(ctx):
    """The names homebrew.brews and homebrew.casks can be filled in from, in choices.json.
    Everything comes from the local brew -- its own lists for the core formulas and casks, plus
    what each tap named in the configuration's homebrew.taps provides (asked for tap by tap:
    brew leaves a tap it doesn't consider trusted out of its combined list). A tap's entries are
    written as tap/name, the form that's unambiguous in a Brewfile. Only an installed tap can be
    listed, so one that was just added to the configuration shows up after the next rebuild.
    A name has its description with it where brew's cache has one (_descriptions()).

    Returns nothing at all without a working brew, leaving whatever was generated before."""
    brew = _brew_command()
    if not brew:
        ctx.note("Homebrew not found — skipping its names in choices.json")
        return None
    ctx.info("Generating Homebrew's names in choices.json...")
    formulae = _brew(ctx, brew, ["formulae"])
    casks = _brew(ctx, brew, ["casks"])
    # No names at all counts as brew not answering, like an error does: an empty list
    # written from an empty answer took the list of formulas out of the editor on the user's
    # Mac (2026-10-11; see _brew() for why the answer was empty), with the casks whole beside it.
    brews = set((formulae or "").split())
    casks = set((casks or "").split())
    if not brews or not casks:
        ctx.warn("could not list Homebrew formulas/casks — leaving choices.json as it was "
             "(rerun with -v for details)")
        return None

    taps = ctx.nix_eval([f"{ctx.flake_ref}.config.homebrew.taps", "--apply", "map (t: t.name or t)"])
    if taps:
        out = _brew(ctx, brew, ["tap-info", "--json"] + taps)
        try:
            tap_info = json.loads(out) if out else []
        except ValueError:
            tap_info = []
        for t in tap_info:
            if not t.get("installed"):
                ctx.info(f"  tap {t.get('name')} is not installed yet — its formulas appear after a rebuild")
                continue
            brews.update(t.get("formula_names") or [])
            casks.update(t.get("cask_tokens") or [])

    brew_descs, cask_descs = _descriptions(ctx, brew)
    ctx.info(f"  {len(brews)} formulas, {len(casks)} casks "
             f"({len(brew_descs)} and {len(cask_descs)} with a description)")
    return {"choices": {"homebrew.brews": {"free": True, "values": _values(brews, brew_descs)},
                        "homebrew.casks": {"free": True, "values": _values(casks, cask_descs)}}}
