// The nixfiles plugin: a "Nix files" button in the header listing every *.nix file in the
// flake. A file opens in an editor of the user's own (vim, nano, whatever is installed), in a
// terminal of its own that is a tab of the plugin's window on the side. nixfiles.py in this
// folder lists the files; the editor does everything else.
//
// The plugin only has to know how to start the editor: its colours, its keys and whatever it
// is set up to do come with it, installed and configured like anything else on the machine.
// It had an editor of its own in the page for some hours on 2026-10-12 (a text field with its
// own colouring, suggestions read off the text by a scanner written for it, Save, Delete and
// backups); once a file could be opened in a terminal the user asked whether any of that was
// still needed, and it was taken out.
//
// The terminal is asked for through the page ('terminal', heard by the terminal panel) and
// runs on a shell of its own, so the one at the bottom stays free for a rebuild. Without a
// terminal there is nothing to open a file in, and no button.

// An icon like its neighbours' (braces, Lucide's "braces") and its name beside it.
const _nixFilesBtn = eznix.addButton('header', {
  id: 'nixfiles-menu-btn', tooltip: 'Edit the .nix files in the flake',
  html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/></svg>Nix files',
  onclick: e => showNixFilesMenu(e),
});
_nixFilesBtn.classList.add('hidden');

const _nixConfig = eznix.config.nixfiles || {};
let _nixFiles = [];
const _nixOpen = new Map();     // the files that are open: name -> its panel
function _nixKeepOpen() {
  try { localStorage.setItem('eznix-nixfiles-open', JSON.stringify([..._nixOpen.keys()])); } catch (e) { /* ignore */ }
}

async function _nixFetchFiles() {
  try {
    const data = await (await apiFetch('/plugin/nixfiles/files')).json();
    _nixFiles = data.files || [];
  } catch (e) { /* keep the list there was */ }
}

// The menu under the button, the way the Documents one is made: each file, with a mark on
// those that are open; choosing one opens it, or brings its tab forward.
async function showNixFilesMenu(event) {
  const btn = event.currentTarget;
  const rect = btn.getBoundingClientRect();
  const anchor = {
    clientX: rect.left, clientY: rect.bottom + 2,
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  await _nixFetchFiles();
  const names = [...new Set([..._nixFiles, ..._nixOpen.keys()])].sort();
  showContextMenu(anchor, [...names.map(name => ({
    label: (_nixOpen.has(name) ? '✓ ' : '') + name,
    onclick: () => openNixFile(name),
  })), ...(names.length ? [{ separator: true }] : []), { label: 'New file…', onclick: newNixFile }], { triggerEl: btn });
}

// A new file: asked for by its path inside the flake, and opened in the editor under it. The
// editor makes the file when it first writes it; a folder that is not there yet is made
// before the editor starts.
function newNixFile() {
  const name = (prompt('The new file, as a path inside the flake:', 'untitled.nix') || '').trim().replace(/^\.?\/+/, '');
  if (!name) return;
  if (!name.endsWith('.nix') || name.split('/').some(part => !part || part === '.' || part === '..')) {
    setStatus('Not a new Nix file: a path inside the flake that ends in .nix', 4000, 'err');
    return;
  }
  openNixFile(name);
}

// Opens a file in the editor, in a terminal that is a tab on the side, or brings the tab it is
// open in forward. The shell is replaced by the editor (`exec`), so leaving the editor ends
// the shell and closes the tab, which is the one way to close it: the tab has no cross (it
// had one, which hung up on the editor with whatever was unsaved in it; the user had it taken
// off, 2026-10-12: "it makes sense that closing the editor closes it"). The shell is named after the file, so that opening a file again, or reloading the
// page, comes back to the same editor (the command is only what a new shell is started on).
function openNixFile(name) {
  if (_nixOpen.has(name)) { _nixOpen.get(name).front(); return; }
  const asked = {};
  const panel = eznix.sidePanel({ group: 'nixfiles', title: name, closable: false, onClose: () => {
    _nixOpen.delete(name); _nixKeepOpen();
    if (asked.close) asked.close();
  } });
  panel.body.classList.add('nixfiles-terminal');
  // Letters, digits and dashes only, as the terminal wants a name: a number made of the path.
  let hash = 5381;
  for (const ch of name) hash = ((hash * 33) ^ ch.codePointAt(0)) >>> 0;
  const quote = text => "'" + text.replace(/'/g, "'\\''") + "'";
  const path = _nixConfig.flake + '/' + name, folder = path.slice(0, path.lastIndexOf('/'));
  const run = 'mkdir -p ' + quote(folder) + ' && exec ' + (_nixConfig.editor || '${EDITOR:-nano}') + ' ' + quote(path);
  Object.assign(asked, { el: panel.body, session: 'nix-' + hash.toString(36), run, onExit: () => panel.close() });
  eznix.emit('terminal', asked);
  // The cursor goes into the editor whenever its tab comes into view.
  panel.focus = () => asked.focus && asked.focus();
  _nixOpen.set(name, panel);
  _nixKeepOpen();
}

eznix.on('ready', async () => {
  if (!eznix.listens('terminal')) return;
  _nixFilesBtn.classList.remove('hidden');
  let open = [];
  try { open = JSON.parse(localStorage.getItem('eznix-nixfiles-open') || '[]'); } catch (e) { /* ignore */ }
  if (Array.isArray(open)) open.forEach(name => { if (typeof name === 'string') openNixFile(name); });
});
