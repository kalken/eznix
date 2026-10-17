"""Autocomplete source: the kernels boot.kernelPackages can be set to.

Run by eznix-autocomplete (see "Plugins" in bin/eznix-autocomplete.py): generate(ctx) returns
what to add to the suggestions. NixOS only; a nix-darwin or home-manager configuration has no
kernel to choose, and the generator then leaves this out without a word."""

SYSTEMS = ("nixos",)

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


def generate(ctx):
    """The kernels boot.kernelPackages can be set to, as expressions (pkgs.linuxPackages_...)."""
    ctx.info("Generating the kernels in choices.json...")
    result = ctx.nix_eval([f"{ctx.flake_ref}.pkgs", "--apply", KERNELS_EXPR])
    if result is None:
        ctx.failed("choices.json", "the kernels could not be evaluated")
        return None
    ctx.info(f"  {len(result)} kernels")
    return {"choices": {"boot.kernelPackages": {"expr": True, "values": [
        {"value": "pkgs." + k["name"], "description": k.get("description")} for k in result]}}}
