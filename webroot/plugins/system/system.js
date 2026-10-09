// The system plugin: export the whole flake as a zip, import one over it, and restore one of
// the automatic backups made before each of those. All three act on the files on disk at
// once -- no Save step, no undo -- which is why they are a plugin: an install that doesn't
// want them leaves it out ([plugin.system] enabled = false). The work itself is done by
// system.py in this folder; this file is the buttons and the confirmations.
const SYSTEM_BACKUP_ENABLED = !!(eznix.config.system || {}).backups;

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
    if (!confirm(
      `Import ${file.name} into ${NIXOS_TARGET}?\n\n` +
      `This writes directly to disk immediately — there is no Save step and no undo (the current ` +
      `state is itself backed up first, so this is recoverable from there, but not from within eznix). ` +
      `Existing files with the same name are overwritten, and anything not in the zip is DELETED, ` +
      `so the tree ends up matching exactly what was imported.`
    )) return;
    try {
      const res = await apiFetch('/plugin/system/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/zip' },
        body: file,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setStatus('Import failed: ' + (data.error || res.status), 5000, 'err'); return; }
      const parts = [`Imported ${data.written.length} file(s) into ${NIXOS_TARGET}`];
      if (data.removed && data.removed.length) parts.push(`removed ${data.removed.length}`);
      if (data.skipped && data.skipped.length) parts.push(`skipped ${data.skipped.length}`);
      // This writes straight into NIXOS_TARGET on disk, which CONFIG_DIR lives under — the
      // in-memory files/fileConfigs state has no way to know its tab list or content might now
      // be stale, so a reload is the only way to pick that up. Same "don't clobber unsaved
      // edits" rule as restart detection: reload immediately only if nothing's dirty, otherwise
      // just say so — the edits themselves are unaffected by this import either way.
      if (isAnyDirty()) {
        setStatus(parts.join(', ') + ' — reload once you save/undo to see the changes', 6000, 'ok');
      } else {
        location.reload();
      }
    } catch (err) {
      setStatus('Import failed: ' + err.message, 5000, 'err');
    }
  });
}

// The Restore button opens a dropdown, not a modal — showContextMenu doesn't care whether it's
// triggered by a right-click or a plain click, so it's reused here as a left-click dropdown menu.
// Used to be split into "File"/"System" submenus, but restoring a specific file's own backup
// moved to that file's tab right-click menu instead (see _makeTab()'s oncontextmenu) — this button
// only ever covers the whole-NIXOS_TARGET case now (see eznix.py's
// backup_system()/_restore_system_zip()), so there's nothing left to choose between; it goes
// straight to the list. Named "Restore" rather than "Backups" since every action in this menu is a
// restore, not a way to make a new backup: there's no manual "back up now" trigger -- a system
// backup is only ever created automatically, right before system-import/system-backup/restore
// overwrites something (see backup_system()'s call sites in eznix.py), so the list here is really
// a history of "state right before the last few destructive writes," which is the only thing a
// backup is actually for. Clicking an entry restores it directly (via restoreSystemBackup()'s own
// confirm()) -- there's no separate download action either, since downloading a system backup for
// its own sake isn't something this app needs to support.
async function showBackupsMenu(event) {
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
    clientX: rect.left, clientY: rect.bottom + 4,
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  let systemBackups = [];
  try {
    const res = await apiFetch('/plugin/system/backups');
    if (res.ok) systemBackups = (await res.json()).backups || [];
  } catch (e) { /* falls through to the empty-state item below */ }
  const items = systemBackups.length
    ? systemBackups.map(b => ({
        label: new Date(b.mtime * 1000).toLocaleString() + '  ·  ' + _formatBackupSize(b.size),
        danger: true,
        onclick: () => restoreSystemBackup(b.name),
      }))
    : [{ label: 'No system backups yet — one is made automatically before any system import or restore.', disabled: true }];
  showContextMenu(anchor, items, { triggerEl: btn });
}

eznix.addMenuItem('export', { label: 'System', title: NIXOS_TARGET, onclick: () => exportSystem() });
eznix.addMenuItem('import', { label: 'System', onclick: () => importSystem() });
eznix.on('init', () => {
  const input = document.createElement('input');
  input.type = 'file'; input.id = 'system-import-input'; input.accept = '.zip';
  document.querySelector('.header-actions').prepend(input);
  initSystemImportButton();
  // Restoring a single file's backup is on that file's tab; this button is the whole system.
  // The icon is the reload button's circular arrow plus a clock hand (Lucide's "history").
  if (SYSTEM_BACKUP_ENABLED) {
    eznix.addButton('header', {
      id: 'restore-btn',
      tooltip: 'Restore the whole system from an automatic backup',
      html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3.5-7.1"/><polyline points="3 3 3 8 8 8"/><path d="M12 7v5l4 2"/></svg> Restore',
      onclick: showBackupsMenu,
    });
  }
});
