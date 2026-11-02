// The uploads plugin: one button in the header, "Upload", as Documents has one. Its menu has a
// heading per target ([plugin.uploads] targets, see uploads.py) with its folder and the endings
// it takes; under it the files in that folder, each with a cross that deletes it, and
// pressing the target line asks the browser for a file and sends it. What is in the folders is read
// each time the menu opens.
const _uploadsConfig = eznix.config.uploads || {};

if ((_uploadsConfig.targets || []).length) {
  eznix.addButton('header', {
    id: 'uploads-btn', tooltip: 'Upload a file to a folder on this machine',
    // Lucide's "upload", with the name beside it as on Documents. It pointed down for a few
    // hours (the user's own mark for a file coming onto the computer) and went back up: the
    // button says "Upload", and an arrow up is what that word means to most people.
    html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>Upload',
    onclick: e => showUploadsMenu(e),
    group: 'files',
  });
}

async function showUploadsMenu(event) {
  const btn = event.currentTarget;
  const rect = btn.getBoundingClientRect();
  const anchor = {
    clientX: rect.left, clientY: rect.bottom + 2, anchorRight: rect.right,
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  let listed = [];
  try {
    listed = (await (await apiFetch('/plugin/uploads/files')).json()).targets || [];
  } catch (e) { /* no files listed, then */ }
  const items = [];
  _uploadsConfig.targets.forEach((target, n) => {
    if (n) items.push({ separator: true });
    // The folder is the line to press. Its files are heading lines (dim, indented, not
    // pressable) with a cross. (It had an arrow down in front for some hours, the user's mark
    // for a file coming onto the computer; the one on the header's button was enough.)
    items.push({
      label: target.name + '  (' + target.extensions.join(', ') + ')',
      title: 'Upload a file to ' + target.dir,
      onclick: () => chooseUpload(target, n),
    });
    (listed[n] || []).forEach(file => items.push({
      heading: true,
      label: '      ' + file.name + '  (' + _uploadsSize(file.size) + ')',
      aside: { label: '✕', title: 'Delete this file', onclick: () => deleteUpload(target, n, file.name) },
    }));
  });
  showContextMenu(anchor, items, { triggerEl: btn });
}

function _uploadsSize(bytes) {
  return bytes < 1024 ? bytes + ' B' : bytes < 1048576 ? Math.round(bytes / 1024) + ' kB' : (bytes / 1048576).toFixed(1) + ' MB';
}

function chooseUpload(target, n) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = target.extensions.join(',');
  input.addEventListener('change', () => { if (input.files[0]) sendUpload(target, n, input.files[0]); });
  input.click();
}

async function sendUpload(target, n, file) {
  if (file.size > target.max_size) {
    setStatus(file.name + ' is over ' + Math.round(target.max_size / 1048576) + ' MB', 5000, 'err');
    return;
  }
  try {
    const res = await apiFetch('/plugin/uploads/upload?target=' + n + '&name=' + encodeURIComponent(file.name), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setStatus('Not uploaded: ' + (data.error || res.status), 6000, 'err'); return; }
    setStatus('Uploaded ' + file.name + ' to ' + target.dir, 4000, 'ok');
  } catch (e) {
    setStatus('Not uploaded: ' + e.message, 6000, 'err');
  }
}

async function deleteUpload(target, n, name) {
  if (!confirm('Delete ' + name + ' from ' + target.dir + ' now?\n\nIt cannot be brought back from here.')) return;
  try {
    const res = await apiFetch('/plugin/uploads/delete?target=' + n + '&name=' + encodeURIComponent(name), { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setStatus('Not deleted: ' + (data.error || res.status), 5000, 'err'); return; }
    setStatus('Deleted ' + name, 3000, 'ok');
  } catch (e) {
    setStatus('Not deleted: ' + e.message, 5000, 'err');
  }
}
