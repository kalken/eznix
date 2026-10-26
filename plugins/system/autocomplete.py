"""Autocomplete source: the settings of the system plugin, as services.eznix.plugins.system.*.

Run by eznix-autocomplete (see "Plugins" in bin/eznix-autocomplete.py). `services.eznix.plugins`
is one option in Nix, "attribute set of attribute set of anything", so the suggestions know
nothing of what a plugin takes: this tells them, for the editor to offer the names, say what
each is and mark what a list entry has to have (`file` and `command` of `generate`). It is only
help for the editor: Nix itself accepts any value there, and what the plugin does with it is in
system.py. It reads nothing from the flake, so it is the same for every system."""

OPTIONS = True          # what it returns goes into options.json

BASE = "services.eznix.plugins.system"


def _option(path, type_, description, default=None, required=False, example=None):
    return {"path": f"{BASE}.{path}" if path else BASE, "type": type_, "description": description,
            "default": default, "example": example, "required": required}


def generate(ctx):
    return {"options": [
        _option("", "submodule", "The system plugin: the whole flake as a zip, out and back in, backups of it, "
                "and systems to import from places named here."),
        _option("backups", "signed integer", "How many backups are kept; 0 for none. One is made by itself before "
                "every import and restore.", default="5"),
        _option("protect", "list of string", "What belongs to this machine and is never touched: not exported, not backed up, never written or removed by an import or a restore. Each entry "
                "is read like a line of a .gitignore. A list of your own replaces the default.",
                default='[ ".git" ]', example='[ ".git" ".direnv" ]'),
        _option("exclude", "list of string", "What an export leaves out: what is this machine's own and should not "
                "travel. An import does not look at it: it replaces everything but what protect names. "
                "Each entry is read like a line of a .gitignore. A list of your own replaces the default.",
                default='[ "hardware-configuration.nix" ]',
                example='[ "hardware-configuration.nix" "flake.lock" "generated" ]'),
        _option("sources", "list of (string or attribute set)", "Where systems can be imported from: an https "
                "address or a path on this machine, of a zip, a folder (every folder in it with a flake.nix is a "
                "system), a folder on GitHub (github.com/OWNER/REPO/tree/BRANCH/PATH) or a JSON index. Written as "
                "{ name, url, add_only }, `name` is the heading in the System menu, and `add_only` adds the files "
                "and removes none.", default="[ ]",
                example='[ { name = "Import from X"; url = "https://example.org/systems.zip"; } ]'),
        _option("generate", "list of (submodule)", "Files to make when an import leaves them missing, each with the "
                "command that makes it. The question before an import lists the ones that will be missing, and "
                "after it the commands are typed into the terminal, one after the other, each only if the one "
                "before worked. A template can carry the list in its own configuration; one from a zip you "
                "upload is not taken. There are no defaults.", default="[ ]",
                example='[ { file = "hardware-configuration.nix"; command = "sudo sh -c \'nixos-generate-config '
                        '--show-hardware-config --no-filesystems > hardware-configuration.nix\'"; } ]'),
        _option("generate.*.file", "string", "The file, relative to the flake: made when it is not there after the "
                "import.", required=True, example="hardware-configuration.nix"),
        _option("generate.*.command", "string", "What makes the file, typed into the terminal, which starts in "
                "the flake's folder: a name without a path lands next to flake.nix.", required=True,
                example="sudo sh -c 'nixos-generate-config --show-hardware-config > hardware-configuration.nix'"),
        _option("open", "list of string", "Files to open once a system is imported, relative to the flake: set in "
                "a template's own configuration, so that importing it shows its README, say. Each opens with "
                "what the page has for its kind (Documents for .md, a menu of the files plugin, a tab for one of "
                "the editor's own files); one that is not there is left out. Taken from any zip, since it runs "
                "nothing; set in the running configuration it does nothing.", default="[ ]",
                example='[ "README.md" ]'),
        _option("enabled", "boolean", "false leaves the plugin out.", default="true"),
    ]}
