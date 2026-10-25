// The system plugin: export the whole flake as a zip, import one over it, back it up on request,
// and restore one of the backups (made by that button, and automatically before every import
// and restore). All of it acts on the files on disk at once -- no Save step, no undo -- which
// is why they are a plugin: an install that doesn't
// want them leaves it out ([plugin.system] enabled = false). The work itself is done by
// system.py in this folder; this file is the buttons and the confirmations.
const SYSTEM_BACKUP_ENABLED = !!(eznix.config.system || {}).backups;
const SYSTEM_SOURCES = !!(eznix.config.system || {}).sources;
// `generate`: what an import says to run when it leaves files missing that something says how
// to make (see _afterSystemImport()). The import reloads the page, so what is to be run is kept
// in the browser's session across the reload and run once the page is up again. The
// suggestions are not generated after an import: the server removes the old system's, and the
// page marks the Autocomplete button for it (since 2026-10-25; the `autocomplete` setting did it before).
const _AFTER_IMPORT = 'eznix-system-after-import';
eznix.on('ready', () => {
  let after = null;
  try { after = JSON.parse(sessionStorage.getItem(_AFTER_IMPORT)); sessionStorage.removeItem(_AFTER_IMPORT); } catch (e) { /* no storage: nothing is asked */ }
  if (after && after.command) setTimeout(() => eznix.emit('run', after.command), 0);
  if (after && after.open) setTimeout(() => _openAfterImport(after.open), 0);
});
// `open`: the files the imported system says to show (services.eznix.plugins.system.open in its
// configuration), each {path} in the flake and `tab` for one of the editor's own files, which
// the page switches to; any other goes out as 'open', for whatever shows its kind.
function _openAfterImport(list) {
  for (const item of list || []) {
    if (item.tab && files.includes(item.tab)) switchFile(item.tab);
    else if (item.path) eznix.emit('open', item.path);
  }
}

// Unlike exportAll() (which zips the in-memory fileConfigs — unsaved edits included, but only
// eznix's own *.json tabs), this is the *on-disk* NIXOS_TARGET tree, flake and all — the server
// walks and zips it directly (GET /api/v1/system-export, see _iter_system_export_files() in
// eznix.py), so it's a plain navigation/download rather than anything built client-side.
function exportSystem() {
  location.href = API_BASE + '/plugin/system/export';
}

// Restores a backup already sitting in SYSTEM_BACKUP_DIR straight to NIXOS_TARGET, in one click --
// POST /api/v1/system-backup/restore, which shares the exact same write/delete logic and
// auto-backup-of-the-current-tree-first safety net as system-import (see _restore_system_zip() in
// eznix.py) -- they differ only in where the zip bytes come from (a file already on disk here,
// a fresh upload there). Confirmed the same way importSystem() is (via initSystemImportButton())
// since it's an equally irreversible direct-disk write, and reloads on success under the same
// "don't clobber unsaved edits" rule everything else that changes NIXOS_TARGET on disk follows.
async function restoreSystemBackup(name) {
  if (!confirm(
    `Restore ${name} into ${NIXOS_TARGET}?\n\n` +
    `This writes directly to disk immediately — there is no Save step and no undo (the current ` +
    `state is itself backed up first, so this is recoverable from there, but not from within eznix). ` +
    `Existing files with the same name are overwritten, and anything not in the backup is DELETED, ` +
    `so the tree ends up matching exactly what was backed up.`
  )) return;
  try {
    const res = await apiFetch('/plugin/system/restore?name=' + encodeURIComponent(name), { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setStatus('Restore failed: ' + (data.error || res.status), 5000, 'err'); return; }
    const parts = [`Restored ${data.written.length} file(s) into ${NIXOS_TARGET}`];
    if (data.removed && data.removed.length) parts.push(`removed ${data.removed.length}`);
    if (data.skipped && data.skipped.length) parts.push(`skipped ${data.skipped.length}`);
    if (isAnyDirty()) {
      setStatus(parts.join(', ') + ' — reload once you save/undo to see the changes', 6000, 'ok');
    } else {
      location.reload();
    }
  } catch (e) {
    setStatus('Restore failed: ' + e.message, 4000, 'err');
  }
}

// Backs the whole flake up now, into the same list Restore offers. It is what is on disk that
// is saved, as with an export, so unsaved edits are not in it -- said in the message, since
// "I backed up before trying this" is exactly when there are some. Nothing to confirm: it
// changes no file of the flake. It can push the oldest backup out, like any new one.
let _backingUp = false;
async function backupSystem() {
  if (_backingUp) return;
  _backingUp = true;
  try {
    const res = await apiFetch('/plugin/system/backup', { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setStatus('Backup failed: ' + (data.error || res.status), 5000, 'err'); return; }
    setStatus(`Backed up ${data.files} file(s) of ${NIXOS_TARGET}` + (isAnyDirty() ? ' as saved on disk — unsaved changes are not in it' : ''), 5000, 'ok');
  } catch (e) {
    setStatus('Backup failed: ' + e.message, 4000, 'err');
  } finally {
    _backingUp = false;
  }
}

// Removes one backup from the list, for good: the ✕ at the end of its line in
// showSystemMenu(). Only the backup goes; the flake isn't touched.
async function deleteSystemBackup(backup) {
  const when = new Date(backup.mtime * 1000).toLocaleString();
  if (!confirm(`Delete the backup of ${when}?\n\nIt cannot be brought back.`)) return;
  try {
    const res = await apiFetch('/plugin/system/delete?name=' + encodeURIComponent(backup.name), { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setStatus('Delete failed: ' + (data.error || res.status), 5000, 'err'); return; }
    setStatus(`Deleted the backup of ${when}`, 4000, 'ok');
  } catch (e) {
    setStatus('Delete failed: ' + e.message, 4000, 'err');
  }
}

// The counterpart to exportSystem(): writes a zip straight into NIXOS_TARGET on disk,
// immediately, via POST /api/v1/system-import — unlike every other import path in this app,
// there's no in-memory model for arbitrary system files to stage as "unsaved," so this can't be
// deferred until Save the way dropping a .json onto the window is. Confirmed explicitly for
// exactly that reason: this is the one import that's actually irreversible through eznix itself.
function importSystem() {
  document.getElementById('system-import-input').click();
}

function initSystemImportButton() {
  document.getElementById('system-import-input').addEventListener('change', async e => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      const post = dry => apiFetch('/plugin/system/import' + (dry ? '?dry=1' : ''), {
        method: 'POST',
        headers: { 'Content-Type': 'application/zip' },
        body: file,
      });
      if (!await _askImport(`Import ${file.name}?\n\nThis replaces the current system. A backup is made first.`, post)) return;
      const res = await post(false);
      _afterSystemImport(res, await res.json().catch(() => ({})));
    } catch (err) {
      setStatus('Import failed: ' + err.message, 5000, 'err');
    }
  });
}

// What an import would do, before it is done (a dry run: nothing is written), as lines under
// the question: a zip without a flake.nix at its top, and a machine that will be without its
// hardware file, with the command that makes one. `post(dry)` makes the request. True when it
// is to go on.
async function _askImport(question, post) {
  const res = await post(true);
  const report = await res.json().catch(() => ({}));
  if (!res.ok) { setStatus('Import failed: ' + (report.error || res.status), 5000, 'err'); return false; }
  const lines = [];
  if (report.flake_nix === false) {
    lines.push('\u26a0 There is no flake.nix at the top level.');
  }
  const missing = (report.generate || []).filter(g => g.missing);
  missing.forEach(g => lines.push(`\u26a0 ${g.file} is missing. It will be created with:\n    ${g.command}`));
  if (report.untrusted_generate && !(report.generate || []).length) lines.push('This zip lists files to create, but commands from an uploaded file are not trusted, so they are ignored.');
  return confirm(question + (lines.length ? '\n\n' + lines.join('\n') : ''));
}

function _afterSystemImport(res, data) {
  if (!res.ok) { setStatus('Import failed: ' + (data.error || res.status), 5000, 'err'); return; }
  const parts = [`Imported ${data.written.length} file(s) into ${NIXOS_TARGET}`];
  if (data.removed && data.removed.length) parts.push(`removed ${data.removed.length}`);
  if (data.skipped && data.skipped.length) parts.push(`skipped ${data.skipped.length}`);
  // This writes straight into NIXOS_TARGET on disk, which CONFIG_DIR lives under — the
  // in-memory files/fileConfigs state has no way to know its tab list or content might now
  // be stale, so a reload is the only way to pick that up. Same "don't clobber unsaved
  // edits" rule as restart detection: reload immediately only if nothing's dirty, otherwise
  // just say so — the edits themselves are unaffected by this import either way.
  // The commands that make the files that are missing, one after the other: each has to work
  // for the next to run.
  const command = (data.generate || []).map(g => `( ${g.command} )`).join(' && ') || null;
  if (isAnyDirty()) {
    setStatus(parts.join(', ') + ' — reload once you save/undo to see the changes', 6000, 'ok');
    if (command) eznix.emit('run', command);
    _openAfterImport((data.open || []).filter(item => !item.tab));
  } else {
    if (command || data.open) { try { sessionStorage.setItem(_AFTER_IMPORT, JSON.stringify({ command, open: data.open })); } catch (e) { /* see above */ } }
    location.reload();
  }
}

// The systems the `sources` setting offers ([plugin.system] sources), as a tree from the
// server: a system is { name, url, path, description }, a folder { name, items } (and both, a
// folder that is a system itself), a source that could not be read { name, error }. Asked
// for when the page is ready and kept, so the menu does not wait for a download; "Check
// again" fetches them anew.
let _systemSources = null;
let _systemSourcesLoading = null;
function loadSystemSources(refresh, only) {
  if (_systemSourcesLoading) return _systemSourcesLoading;
  _systemSourcesLoading = (async () => {
    try {
      const res = await apiFetch('/plugin/system/sources' + (refresh ? '?refresh=1' + (only != null ? '&only=' + only : '') : ''));
      const data = await res.json().catch(() => ({}));
      _systemSources = res.ok ? data.sources : [{ name: 'sources', error: data.error || String(res.status) }];
    } catch (e) {
      _systemSources = [{ name: 'sources', error: e.message }];
    } finally {
      _systemSourcesLoading = null;
    }
  })();
  return _systemSourcesLoading;
}

async function importSystemSource(system) {
  const about = system.description ? `\n\n${system.description}` : '';
  const sure = system.add_only
    ? `Start from ${system.name}?${about}\n\nIts files are added to the current system and nothing is removed. A backup is made first.`
    : `Import ${system.name}?${about}\n\nThis replaces the current system. A backup is made first.`;
  try {
    const post = dry => apiFetch('/plugin/system/import-source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: system.url, path: system.path, add_only: system.add_only === true, dry }),
    });
    if (!await _askImport(sure, post)) return;
    setStatus('Importing ' + system.name + '…', 30000);
    const res = await post(false);
    _afterSystemImport(res, await res.json().catch(() => ({})));
  } catch (err) {
    setStatus('Import failed: ' + err.message, 5000, 'err');
  }
}

// The systems of a source as rows of a table in a dialog of their own, each named by its
// folders ("templates/nixos") with its description beside it, and a field that narrows them
// down. They were lines of the System menu, a heading per source (2026-10-19; not submenus: the
// menu hangs from a button at the window's right edge, so a submenu opened on the left, a box
// out over the page, which the user found very strange), until the user asked for them to be
// listed nicer, in a table (2026-10-23): the menu has one line per source now.
function _sourceRows(node, name, out) {
  if (node.error) { out.push({ name, error: node.error }); return out; }
  if (node.url) out.push({ name, system: node });
  (node.items || []).forEach(n => _sourceRows(n, name ? name + '/' + n.name : n.name, out));
  return out;
}

// A source as one card, in the editor's card look (system.css): its name as the title, and each of its
// systems under it, named by its folders ("templates/nixos") with its description, a divider
// between them. A press on a system imports it. `words`: what narrows the systems down, all of
// them to be in a name or description; null when none is left.
function _sourceCard(src, words) {
  const rows = [];
  if (!src.items) rows.push({ name: src.name, system: src });
  else src.items.forEach(n => _sourceRows(n, n.name, rows));
  const shown = rows.filter(r => r.system && words.every(w => (r.name + ' ' + (r.system.description || '')).toLowerCase().includes(w)));
  if (!shown.length) return null;
  const card = document.createElement('div');
  card.className = 'system-card';
  const title = document.createElement('div');
  title.className = 'system-card-title';
  title.textContent = src.name;
  card.appendChild(title);
  for (const r of shown) {
    const item = document.createElement('div');
    item.className = 'system-item';
    const name = document.createElement('div');
    name.className = 'sys-name';
    name.textContent = r.name;
    item.appendChild(name);
    if (r.system.description) {
      const about = document.createElement('div');
      about.className = 'sys-desc';
      about.textContent = r.system.description;
      item.appendChild(about);
    }
    // The page's own tooltip, as the other buttons have, not the browser's title box: where the
    // system comes from (its description is on the card already).
    _wireHoverTooltip(item, r.system.path ? r.system.url + '\n' + r.system.path : r.system.url);
    item.onclick = () => { const o = card.closest('.modal-overlay'); if (o) o.remove(); importSystemSource(r.system); };
    card.appendChild(item);
  }
  return card;
}

function showSystemCards(source) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML =
    '<div class="modal system-cards-modal">' +
      '<input type="text" class="modal-input" placeholder="Search" spellcheck="false" autocomplete="off" aria-label="Search the systems">' +
      '<div class="system-cards"></div>' +
      '<div class="modal-actions"><button class="btn">Cancel</button></div></div>';
  const [search, body, actions] = overlay.firstChild.children;
  const close = () => overlay.remove();
  const draw = () => {
    body.innerHTML = '';
    const card = _sourceCard(source, search.value.toLowerCase().split(/\s+/).filter(Boolean));
    if (card) body.appendChild(card);
    else {
      const none = document.createElement('div');
      none.className = 'modal-hint';
      none.textContent = 'Nothing matches.';
      body.appendChild(none);
    }
  };
  search.oninput = draw;
  actions.firstChild.onclick = close;
  overlay.onmousedown = e => { if (e.target === overlay) close(); };
  overlay.onkeydown = e => { if (e.key === 'Escape') close(); };
  draw();
  document.body.appendChild(overlay);
  search.focus();
}

async function _checkSourcesAgain(only) {
  setStatus('Checking the sources again…', 30000);
  await loadSystemSources(true, only);
  const failed = _systemSources.filter(s => s.error).length;
  setStatus(failed ? `${failed} source(s) could not be read` : 'The sources are up to date', 4000, failed ? 'err' : 'ok');
}

function _sourceMenuItems(again) {
  if (!SYSTEM_SOURCES) return [];
  if (!_systemSources) {
    loadSystemSources();
    return [{ label: 'Loading…', heading: true }];
  }
  // A source is a line named as the setting names it, with the mark at its end that downloads
  // it again: one that is a single system imports it, any other opens the table of its systems.
  const items = [];
  _systemSources.forEach((s, i) => {
    const aside = { label: '↻', title: 'Download this source again', stay: true,
                    onclick: async () => { await _checkSourcesAgain(i); await again(); } };
    if (s.error) items.push({ label: s.name + ': ' + s.error, disabled: true, aside });
    else if (!s.items) items.push({ label: s.name, title: s.description || s.path || s.url, onclick: () => importSystemSource(s), aside });
    else items.push({ label: s.name + '…', title: 'Choose one of its systems', onclick: () => showSystemCards(s), aside });
  });
  return items;
}

// One button, System, opening a dropdown with everything this plugin does: Export, Import, Backup,
// and the backups to restore. showContextMenu doesn't care whether it's
// triggered by a right-click or a plain click, so it's reused here as a left-click dropdown.
// They were four things in the header until 2026-10 (a Backup and a Restore button of this
// plugin's, and a "System" entry in the page's own Import and Export menus beside "Files"):
// the user wanted one button, and the files' import and export left to the tabs' menus.
//
// Restore's list holds the backups made with Backup and the ones made automatically right
// before an import or a restore overwrites something, so it is mostly a history of "state
// right before the last few destructive writes". Clicking an entry restores it directly (via
// restoreSystemBackup()'s own confirm()) -- there's no separate download action, since
// downloading a system backup for its own sake isn't something this app needs to support.
// Restoring a single file's backup is on that file's tab; this is the whole system.
async function showSystemMenu(event) {
  // showContextMenu positions itself at event.clientX/clientY — for a right-click that's exactly
  // the cursor, which is fine, but for this left-click button it'd be wherever inside the button
  // you happened to click. Anchor to the button's own bottom-left corner instead, like a normal
  // dropdown, by capturing its rect (and the button itself, for the toggle-to-close behavior)
  // now — currentTarget is only valid during dispatch, so this has to happen before the await
  // below empties it out — and feeding showContextMenu a lookalike event with that position
  // instead of the real click coordinates.
  const btn = event.currentTarget;
  const rect = btn.getBoundingClientRect();
  const anchor = {
    clientX: rect.left, clientY: rect.bottom + 2, anchorRight: rect.right,   // the same gap the terminal bar's menus have: see _positionMenuAboveAnchor()
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  return renderSystemMenu(anchor, btn, false);
}

// The menu itself, built from what is on the server now. `reopen`: it is being drawn again in
// place after something in it was done (a backup deleted, a source downloaded again), which
// the menu stays open for.
async function renderSystemMenu(anchor, btn, reopen) {
  const again = async () => { if (_openMenuTriggerEl === btn) await renderSystemMenu(anchor, btn, true); };
  // Import, Export, Backup, the systems of the sources, then the backups to restore: the order the user asked for, as a
  // file's right-click menu has the first two (Export stood first until 2026-10-13), which
  // also puts the one part whose length varies last.
  const items = [];
  let systemBackups = [];
  if (SYSTEM_BACKUP_ENABLED) {
    try {
      const res = await apiFetch('/plugin/system/backups');
      if (res.ok) systemBackups = (await res.json()).backups || [];
    } catch (e) { /* falls through to the empty-state item below */ }
  }
  items.push({ label: 'Import', title: 'Replace ' + NIXOS_TARGET + ' with the contents of a zip', onclick: () => importSystem() });
  items.push({ label: 'Export', title: NIXOS_TARGET + ', as a zip', onclick: () => exportSystem() });
  if (SYSTEM_BACKUP_ENABLED) items.push({ label: 'Backup', title: 'Back up the whole system now, as it is on disk', onclick: backupSystem });
  if (SYSTEM_BACKUP_ENABLED) {
    items.push({ separator: true });
    // The backups are lines of this menu, under a heading, and not a submenu of a "Restore"
    // entry as they first were: the button is at the window's right edge, so the submenu had
    // to open on the left, a lone box out over the tab bar, which looked strange to the user.
    items.push({ label: systemBackups.length ? 'Restore' : 'Restore: no backups yet', disabled: true });
    systemBackups.forEach(b => items.push({
      label: new Date(b.mtime * 1000).toLocaleString() + '  ·  ' + _formatBackupSize(b.size),
      danger: true,
      title: 'Restore this backup',
      onclick: () => restoreSystemBackup(b.name),
      aside: { label: '✕', title: 'Delete this backup', stay: true,
               onclick: async () => { await deleteSystemBackup(b); await again(); } },
    }));
  }
  // The sources come last, under Restore.
  const more = _sourceMenuItems(again);
  if (more.length) items.push({ separator: true }, ...more);
  showContextMenu(anchor, items, { triggerEl: btn, reopen });
}

// With no files at all, the editor says so; a whole system is the other way to start.
eznix.on('empty', el => {
  const line = document.createElement('div');
  const link = document.createElement('a');
  link.href = '#';
  link.textContent = 'System \u25b8 Import';
  link.onclick = e => { e.preventDefault(); importSystem(); };
  line.append('A whole system can be imported through ', link, '.');
  el.appendChild(line);
  // The systems the sources offer, as links under it, once they are known.
  if (!SYSTEM_SOURCES) return;
  const list = document.createElement('div');
  list.className = 'system-list';
  el.appendChild(list);
  // A card per source, as in the dialog (links in one running line, then one to a line, until the
  // user asked for cards, 2026-10-23).
  const fill = () => {
    (_systemSources || []).forEach(src => {
      const card = src.error ? null : _sourceCard(src, []);
      if (card) list.appendChild(card);
    });
  };
  if (_systemSources) fill(); else loadSystemSources().then(fill);
});

eznix.on('ready', () => { if (SYSTEM_SOURCES) loadSystemSources(); });

eznix.on('init', () => {
  const input = document.createElement('input');
  input.type = 'file'; input.id = 'system-import-input'; input.accept = '.zip';
  document.querySelector('.header-actions').prepend(input);
  initSystemImportButton();
  // The icon is a disk drive (Lucide's "hard-drive"), with the name beside it as on Documents.
  // Joined with Autocomplete ('system', after 'tools'), the user's layout of 2026-10-19.
  eznix.addButton('header', {
    id: 'system-btn',
    tooltip: 'Back up, restore, import or export the whole system',
    html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/></svg>System',
    onclick: showSystemMenu,
    group: 'system',
  });
});
