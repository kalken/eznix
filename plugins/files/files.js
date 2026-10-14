// The files plugin: menus of the flake's files by their kind, each a button in the header.
// What menus there are is configuration ([plugin.files], see files.py): a name, the endings
// of the files it lists, and the command a file is opened with. With nothing set there is
// one, "Nix files", of the .nix files.
//
// A file opens in that command, in a terminal of its own that is a tab on the side: an
// editor of the user's own (vim, nano, whatever is installed and however it is set up), with
// its colours, its keys and its way of saving. The plugin only has to know how to start it.
// The terminal is asked for through the page ('terminal', heard by the terminal panel) and
// runs on a shell of its own, so the one at the bottom stays free for a rebuild. Without a
// terminal there is nothing to open a file in, and no button.
//
// It was `nixfiles`, for .nix files and one editor, for some hours on 2026-10-12, and before
// that the same day an editor of its own in the page (a text field with colouring,
// suggestions, Save, Delete and backups), taken out once a file could be opened in a
// terminal. The user then asked for this, the general thing: any kinds of file, each in a
// menu of its own name with its own command.
const _filesConfig = eznix.config.files || {};
const _filesOpen = new Map();     // the files that are open: path -> its panel

// A button per menu, in the order they are configured (each is put in front of the last, so
// they are made from the last on), with an icon like its neighbours' (a page, Lucide's
// "file") and its name beside it.
const _filesButtons = (_filesConfig.menus || []).map((menu, n) => [menu, n]).reverse().map(([menu, n]) => {
  const btn = eznix.addButton('header', {
    tooltip: 'Open one of the flake\'s ' + menu.extensions.join(', ') + ' files',
    html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h6"/></svg><span></span>',
    onclick: e => showFilesMenu(e, menu, n),
  });
  btn.querySelector('span').textContent = menu.name;
  btn.classList.add('hidden');
  return btn;
});

// What is listed is read each time a menu is opened, so a file made meanwhile is there.
let _filesFolders = [];     // the flake's folders, each ending in "/": what a new file's path is completed from
async function showFilesMenu(event, menu, n) {
  const btn = event.currentTarget;
  const rect = btn.getBoundingClientRect();
  const anchor = {
    clientX: rect.left, clientY: rect.bottom + 2,
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  let names = [];
  try {
    const data = await (await apiFetch('/plugin/files/files')).json();
    names = (data.menus || [])[n] || [];
    _filesFolders = (data.folders || []).map(f => f + '/');
  } catch (e) { /* an empty list, then */ }
  showContextMenu(anchor, [...names.map(name => ({
    label: (_filesOpen.has(name) ? '✓ ' : '') + name,
    onclick: () => openFlakeFile(name, menu),
    aside: { label: '✕', title: 'Delete this file', onclick: () => deleteFlakeFile(name) },
  })), ...(names.length ? [{ separator: true }] : []), { label: 'New file…', onclick: () => newFlakeFile(menu, names) }], { triggerEl: btn });
}

// The cross at the end of a file's line in a menu: deletes the file from disk, at once, after
// asking. There is no copy and no undo, which the question says. A tab the file is open in is
// closed first, which hangs up on the program there. (The page's own editor of the plugin's
// first hours had a Delete; with a program of the user's in a terminal there was none, and
// the user asked for this.)
async function deleteFlakeFile(name) {
  if (!confirm('Delete ' + name + ' from disk now?\n\nIt cannot be brought back from here.')) return;
  if (_filesOpen.has(name)) _filesOpen.get(name).close();
  try {
    const res = await apiFetch('/plugin/files/delete?name=' + encodeURIComponent(name), { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setStatus('Not deleted: ' + (data.error || res.status), 5000, 'err'); return; }
    setStatus('Deleted ' + name, 3000, 'ok');
  } catch (e) {
    setStatus('Not deleted: ' + e.message, 5000, 'err');
  }
}

// A new file: a small dialog of the page's own kind asks for its path inside the flake, and it
// is opened under that. Nothing is made here: the program makes the file when it first writes
// it, and a folder that is not there yet is made before it starts (`mkdir` in front of the
// program, only then), which the line under the field says while the path is typed. The
// flake's folders are offered under the field as the path is typed, in the look of the add
// field's list: those that go on from what stands before the last "/" and begin with what is
// typed after it. The name has to end in one of the menu's endings. (It was the browser's own
// prompt() at first, which the user asked to have made nicer, 2026-10-12. Until 2026-10-14
// the first ending was put on a name without one, and every file was opened behind a `mkdir
// -p` of its folder; the user wanted the ending typed, the new folder said, and a plain open
// of what is there.)
function newFlakeFile(menu, existing) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML =
    '<div class="modal files-new"><h2></h2>' +
      '<div class="files-new-path"><input type="text" spellcheck="false" autocomplete="off" aria-label="Path inside the flake">' +
        '<div class="autocomplete-list hidden"></div></div>' +
      '<p class="files-new-hint"></p>' +
      '<div class="modal-actions"><button class="btn">Cancel</button><button class="btn primary">Create</button></div></div>';
  const [title, pathWrap, hint, actions] = overlay.firstChild.children;
  const input = pathWrap.firstChild, list = pathWrap.lastChild, [cancelBtn, createBtn] = actions.children;
  const endings = menu.extensions;
  title.textContent = 'New file in ' + menu.name;
  input.placeholder = 'folder/name' + endings[0];
  const plain = 'A path inside the flake, ending in ' + endings.join(' or ') + '.';
  const say = (text, isError) => { hint.textContent = text; hint.classList.toggle('is-error', !!isError); };
  // The folders of the path that are not there yet, from the first one missing, and the one
  // they go in: null when there are none. What the menu lists counts as there (the flake's
  // folders, less what is excluded).
  const newFolders = value => {
    const parts = value.trim().replace(/^\.?\/+/, '').split('/').slice(0, -1);
    for (let n = 0; n < parts.length; n++)
      if (!_filesFolders.includes(parts.slice(0, n + 1).join('/') + '/'))
        return { made: parts.slice(n).join('/') + '/', inside: parts.slice(0, n).join('/') };
    return null;
  };
  const describe = () => {
    const found = newFolders(input.value);
    say(found ? plain + ' Creates the folder ' + found.made + (found.inside ? ' in ' + found.inside + '/' : '') + '.' : plain);
  };
  say(plain);
  const close = () => overlay.remove();

  let index = -1;
  const hideList = () => { list.classList.add('hidden'); index = -1; };
  const pick = folder => { input.value = folder; input.focus(); describe(); showList(); };
  function showList() {
    const value = input.value, cut = value.lastIndexOf('/') + 1;
    const prefix = value.slice(0, cut), partial = value.slice(cut).toLowerCase();
    const found = _filesFolders.filter(f => f.startsWith(prefix) && f.length > prefix.length && f.slice(cut).toLowerCase().startsWith(partial)).slice(0, 40);
    list.innerHTML = '';
    index = -1;
    for (const folder of found) {
      const el = document.createElement('div');
      el.className = 'autocomplete-item';
      const label = document.createElement('span');
      label.className = 'ac-name'; label.textContent = folder;
      el.appendChild(label);
      el.addEventListener('mousedown', e => { e.preventDefault(); pick(folder); });
      list.appendChild(el);
    }
    list.classList.toggle('hidden', !found.length);
  }
  function create() {
    let name = input.value.trim().replace(/^\.?\/+/, '');
    if (!name || name.endsWith('/')) { say('The file needs a name.', true); return; }
    if (!endings.some(ending => name.endsWith(ending) && name.length > ending.length)) { say('The name has to end in ' + endings.join(' or ') + '.', true); return; }
    if (name.split('/').some(part => !part || part === '.' || part === '..')) { say('Not a path inside the flake.', true); return; }
    if (existing.includes(name)) { say(name + ' is there already.', true); return; }
    close();
    openFlakeFile(name, menu, !!newFolders(name));
  }
  input.addEventListener('input', () => { describe(); showList(); });
  input.addEventListener('blur', hideList);
  input.addEventListener('keydown', e => {
    const items = [...list.children], open = !list.classList.contains('hidden');
    if (open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      index = e.key === 'ArrowDown' ? (index + 1) % items.length : (Math.max(index, 0) + items.length - 1) % items.length;
      items.forEach((el, n) => el.classList.toggle('active', n === index));
      items[index].scrollIntoView({ block: 'nearest' });
    } else if (open && (e.key === 'Tab' || (e.key === 'Enter' && index >= 0))) {
      // Tab takes the first when none is marked, as in a shell.
      e.preventDefault();
      pick(items[Math.max(0, index)].textContent);
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      if (open) hideList(); else close();
    } else if (e.key === 'Enter') {
      e.preventDefault(); create();
    }
  });
  cancelBtn.onclick = close;
  createBtn.onclick = create;
  // A press on the dimmed page around the dialog closes it, as it does the page's other one.
  overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
  document.body.appendChild(overlay);
  input.focus();
}

// Opens a file with its menu's command, in a terminal that is a tab on the side, or brings the
// tab it is open in forward. The shell is replaced by the program (`exec`), so leaving the
// program ends the shell and closes the tab. The tab's cross closes it too, and hangs up on
// the program as closing a terminal window does, with no question: an editor keeps what was
// unsaved in a recovery file of its own (vim's swap file) and offers it when the file is next
// opened, which the user found to be enough. (There was no cross for a while, and one that
// asked first, 2026-10-12.) The shell
// is named after the file, so that opening a file again, or reloading the page, comes back to
// the same program (the command is only what a new shell is started on).
function openFlakeFile(name, menu, newFolder) {
  if (_filesOpen.has(name)) { _filesOpen.get(name).front(); return; }
  const asked = {};
  const panel = eznix.sidePanel({ group: 'files', title: name, autoHide: _filesConfig.auto_hide !== false, onClose: () => {
    _filesOpen.delete(name); _filesKeepOpen();
    if (asked.close) asked.close();
  } });
  panel.body.classList.add('files-terminal');
  panel.menu = menu.name;
  // Letters, digits and dashes only, as the terminal wants a name: a number made of the path.
  let hash = 5381;
  for (const ch of name) hash = ((hash * 33) ^ ch.codePointAt(0)) >>> 0;
  const quote = text => "'" + text.replace(/'/g, "'\\''") + "'";
  const path = _filesConfig.flake + '/' + name, folder = path.slice(0, path.lastIndexOf('/'));
  // A folder is made only for a new file whose folder is not there (newFlakeFile()).
  const run = (newFolder ? 'mkdir -p ' + quote(folder) + ' && ' : '') + 'exec ' + (menu.command || '${EDITOR:-nano}') + ' ' + quote(path);
  Object.assign(asked, { el: panel.body, session: 'file-' + hash.toString(36), run, onExit: () => panel.close() });
  eznix.emit('terminal', asked);
  // The cursor goes into the program whenever its tab comes into view.
  panel.focus = () => asked.focus && asked.focus();
  _filesOpen.set(name, panel);
  _filesKeepOpen();
}
// What is open is kept for a reload of the page, with the menu each was opened from.
function _filesKeepOpen() {
  try { localStorage.setItem('eznix-files-open', JSON.stringify([..._filesOpen].map(([name, panel]) => [name, panel.menu]))); } catch (e) { /* ignore */ }
}

eznix.on('ready', () => {
  if (!eznix.listens('terminal')) return;
  _filesButtons.forEach(btn => btn.classList.remove('hidden'));
  let open = [];
  try { open = JSON.parse(localStorage.getItem('eznix-files-open') || '[]'); } catch (e) { /* ignore */ }
  if (!Array.isArray(open)) return;
  for (const entry of open) {
    const menu = Array.isArray(entry) && (_filesConfig.menus || []).find(m => m.name === entry[1]);
    if (menu && typeof entry[0] === 'string') openFlakeFile(entry[0], menu);
  }
});
