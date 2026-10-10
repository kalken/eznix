// The documents plugin: a "Documents" button in the header listing every *.md file in the
// flake, each opening as a panel floating over the editor. documents.py in this folder lists
// and reads the files; everything else is here.
document.querySelector('.main').insertAdjacentHTML('beforeend', '<div class="markdown-panels" id="markdown-panels"></div>');
// In the header beside Backup/Restore/Import/Export, with an icon like theirs (a page with
// lines, Lucide's "file-text") and its name, which the user asked to keep beside the icon. It was a button reading "Documents" at the end of the tab bar until
// 2026-10, when the user wanted it on the row with those.
const _mdMenuBtn = eznix.addButton('header', {
  id: 'md-menu-btn', tooltip: 'Browse .md files in the flake',
  html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>Documents',
  onclick: e => showMarkdownMenu(e),
});
_mdMenuBtn.classList.add('hidden');

// Minimal Markdown → HTML parser, no dependencies — ported near-verbatim from
// github.com/kalken/ezblog's app.js (same zero-dependency philosophy as this project). Raw HTML
// in the source passes through unescaped outside of code spans/blocks, same as that source —
// acceptable here since these files come straight from NIXOS_TARGET's root, which an
// authenticated eznix user already has full local access to (see resolve_config_path()'s "not
// a security boundary" note).
function parseMarkdown(text) {
  const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Stash fenced code blocks before any other processing
  const stash = [];
  const stashPush = s => { stash.push(s); return `\x02${stash.length - 1}\x03`; };
  const stashPop = s => s.replace(/\x02(\d+)\x03/g, (_, i) => stash[+i]);

  text = text.replace(/^```(\w*)\n([\s\S]*?)^```/gm, (_, lang, code) =>
    stashPush(`<pre><code${lang ? ` class="language-${lang}"` : ''}>${escape(code.trimEnd())}</code></pre>`)
  );

  function inline(s) {
    return stashPop(s
      // target="_blank" on every link (both here and the text-link replace below) is what keeps
      // a genuine external/unhandled link from navigating this SPA tab away to a dead URL
      // (nothing here serves arbitrary NIXOS_TARGET files, image links included) -- the doc-to-doc
      // case below is instead caught and preventDefault()-ed by a click handler before the
      // browser ever acts on href/target at all, so this is just the safe fallback for everything
      // that handler doesn't recognize as one of the open document's own siblings.
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => { const s = src.replace(/^\.\.\//, ''); return `<a href="${s}" target="_blank" rel="noopener noreferrer"><img alt="${alt}" src="${s}"></a>`; })
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/`([^`]+)`/g, (_, c) => `<code>${escape(c)}</code>`)
      .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
      .replace(/~~(.+?)~~/g, '<del>$1</del>')
    );
  }

  const lines = text.split('\n');
  const out = [];
  let i = 0;

  const isBlock = l =>
    /^#{1,6}\s/.test(l) ||
    /^[-*+]\s/.test(l) ||
    /^\d+\.\s/.test(l) ||
    /^>\s/.test(l) ||
    /^(?:---|\*\*\*|___)\s*$/.test(l) ||
    /^\x02\d+\x03$/.test(l.trim());

  while (i < lines.length) {
    const line = lines[i];

    // Stashed code block
    if (/^\x02\d+\x03$/.test(line.trim())) {
      out.push(stashPop(line.trim()));
      i++;
      continue;
    }

    // Heading — id is a GitHub-style slug of the heading text, so an in-doc or cross-doc link
    // (e.g. "[setup](./install.md#configuration)") has something to actually scroll to; see
    // _resolveMdLink()/the click handler in openMarkdownFile() for how that fragment is used.
    const hm = line.match(/^(#{1,6})\s+(.+)/);
    if (hm) {
      const lvl = hm[1].length;
      const text = hm[2];
      const slug = text.toLowerCase().replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-');
      out.push(`<h${lvl} id="${escape(slug)}">${inline(text)}</h${lvl}>`);
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(?:---|\*\*\*|___)\s*$/.test(line)) {
      out.push('<hr>');
      i++;
      continue;
    }

    // Blockquote
    if (/^>\s?/.test(line)) {
      const bq = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        bq.push(lines[i].replace(/^>\s?/, ''));
        i++;
      }
      out.push(`<blockquote>${parseMarkdown(bq.join('\n'))}</blockquote>`);
      continue;
    }

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^[-*+]\s/, ''))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\d+\.\s/, ''))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    // Table (GFM-style): a header row immediately followed by a delimiter row of only -, :, |,
    // and whitespace (e.g. "|---|:---:|"). Every row is trimmed and has its leading/trailing pipe
    // stripped before being split on '|' -- trimming is also what makes a row with odd/inconsistent
    // leading whitespace (e.g. reflowed by whatever it was pasted from) still parse as a normal
    // row instead of falling out of the table. Alignment from the delimiter row's colons becomes
    // an inline text-align style per cell, since there's no separate CSS class for it.
    const isDelimiterRow = l => {
      const t = l.trim().replace(/^\|/, '').replace(/\|$/, '');
      return t.length > 0 && /^:?-+:?(\s*\|\s*:?-+:?)*$/.test(t);
    };
    if (line.includes('|') && i + 1 < lines.length && isDelimiterRow(lines[i + 1])) {
      const splitRow = l => {
        let t = l.trim();
        if (t.startsWith('|')) t = t.slice(1);
        if (t.endsWith('|')) t = t.slice(0, -1);
        return t.split('|').map(c => c.trim());
      };
      const headerCells = splitRow(line);
      const aligns = splitRow(lines[i + 1]).map(c => {
        if (c.startsWith(':') && c.endsWith(':')) return 'center';
        if (c.endsWith(':')) return 'right';
        if (c.startsWith(':')) return 'left';
        return '';
      });
      i += 2;
      const bodyRows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
        bodyRows.push(splitRow(lines[i]));
        i++;
      }
      const cellAttr = idx => aligns[idx] ? ` style="text-align:${aligns[idx]}"` : '';
      const thead = `<tr>${headerCells.map((c, idx) => `<th${cellAttr(idx)}>${inline(c)}</th>`).join('')}</tr>`;
      const tbody = bodyRows.map(cells =>
        `<tr>${cells.map((c, idx) => `<td${cellAttr(idx)}>${inline(c)}</td>`).join('')}</tr>`
      ).join('');
      out.push(`<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`);
      continue;
    }

    // Blank line
    if (!line.trim()) {
      i++;
      continue;
    }

    // Paragraph — collect until blank line or block element
    const p = [];
    while (i < lines.length && lines[i].trim() && !isBlock(lines[i])) {
      p.push(lines[i]);
      i++;
    }
    if (p.length) out.push(`<p>${inline(p.join(' '))}</p>`);
  }

  return out.join('\n');
}

// The Docs button/wrapper starts hidden in markup — initMarkdownMenu() (called once at page
// load) reveals it only if NIXOS_TARGET's root actually has at least one *.md file, since
// there's nothing to browse otherwise. That initial list is only used for this visibility check
// and for restoring whichever docs were open on last visit — showMarkdownMenu() below
// re-fetches fresh every time the dropdown opens, so a file added/removed on disk after page
// load shows up without a reload.
//
// Multiple files can be open at once, each its own floating panel (see #markdown-panels in the
// markup and .markdown-panel/.markdown-panels in style.css) — _openMarkdownPanels maps an open
// file's name to its panel element, doubling as "is this file currently open". Content is
// fetched fresh every time a panel is opened (openMarkdownFile()), not cached, so reopening a
// file after editing it on disk shows the current content.
let _markdownFiles = [];
// Iteration order doubles as stacking order — last entry is frontmost. Map preserves insertion
// order, and deleting + re-setting an existing key moves it to the end, which is exactly what
// _bringMarkdownPanelToFront() below needs to "raise" a panel.
const _openMarkdownPanels = new Map();
function _persistOpenMarkdownDocs() {
  localStorage.setItem('eznix-markdown-open', JSON.stringify([..._openMarkdownPanels.keys()]));
}

// Cascades open panels so each one behind the front peeks out instead of sitting fully hidden
// underneath — that sliver is always clickable (_bringMarkdownPanelToFront) so any open file
// stays reachable regardless of how many are open. Only the raw per-panel index is computed
// here; the actual px-per-step arithmetic lives in .markdown-panel's own transform (style.css),
// driven by this --from-front custom property.
function _layoutMarkdownPanels() {
  const entries = [..._openMarkdownPanels.values()];
  const n = entries.length;
  entries.forEach((panel, i) => {
    panel.style.zIndex = i + 1;
    panel.style.setProperty('--from-front', n - 1 - i);
  });
}

function _bringMarkdownPanelToFront(name) {
  const panel = _openMarkdownPanels.get(name);
  if (!panel) return;
  _openMarkdownPanels.delete(name);
  _openMarkdownPanels.set(name, panel);
  _layoutMarkdownPanels();
  _persistOpenMarkdownDocs();
}

async function initMarkdownMenu() {
  try {
    const res = await apiFetch('/plugin/documents/files');
    const data = await res.json();
    _markdownFiles = data.files || [];
  } catch (e) {
    _markdownFiles = [];
  }
  _mdMenuBtn.classList.toggle('hidden', !_markdownFiles.length);
  if (!_markdownFiles.length) return;
  let openNames = [];
  try { openNames = JSON.parse(localStorage.getItem('eznix-markdown-open') || '[]'); } catch (e) { /* ignore */ }
  openNames.filter(name => _markdownFiles.includes(name)).forEach(openMarkdownFile);
}

// Same left-click-reuses-showContextMenu trick as the system plugin's menu — anchored to the button's
// own bottom-left corner like a normal dropdown. Re-fetches the file list on every open (unlike
// the initial load-time fetch in initMarkdownMenu()) so it reflects the current state of
// NIXOS_TARGET's root, not just whatever existed when the page loaded. Each item toggles that
// file's panel open/closed rather than replacing whatever's already open, so picking several in
// a row opens several panels side by side.
async function showMarkdownMenu(event) {
  const btn = event.currentTarget;
  const rect = btn.getBoundingClientRect();
  const anchor = {
    clientX: rect.left, clientY: rect.bottom + 4,
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  try {
    const res = await apiFetch('/plugin/documents/files');
    const data = await res.json();
    _markdownFiles = data.files || [];
  } catch (e) { /* keep the previous list on a fetch failure */ }
  _mdMenuBtn.classList.toggle('hidden', !_markdownFiles.length);
  if (!_markdownFiles.length) {
    showContextMenu(anchor, [{ label: 'No .md files found.', disabled: true }], { triggerEl: btn });
    return;
  }
  showContextMenu(anchor, _markdownFiles.map(name => ({
    label: (_openMarkdownPanels.has(name) ? '✓ ' : '') + name,
    onclick: () => _openMarkdownPanels.has(name) ? closeMarkdownPanel(name) : openMarkdownFile(name),
  })), { triggerEl: btn });
}

// Resolves a link's href found inside the document at `basePath` (a NIXOS_TARGET-relative path,
// same convention as _markdownFiles/openMarkdownFile's own `name`) to another NIXOS_TARGET-
// relative path, the way a real relative link resolves against the file it's written in rather
// than against NIXOS_TARGET's root — e.g. "../other.md" from "services/nginx/README.md" resolves
// to "services/other.md", not "../other.md" taken literally. Splits off a trailing '#fragment'
// first since that's not part of the path. http(s)/mailto/protocol-relative links are reported as
// `external` rather than resolved — those are for the browser to handle (see inline()'s
// target="_blank"), not something eznix has any other copy of to open in a panel.
function _resolveMdLink(basePath, href) {
  const hashIdx = href.indexOf('#');
  const fragment = hashIdx >= 0 ? href.slice(hashIdx + 1) : '';
  const pathPart = hashIdx >= 0 ? href.slice(0, hashIdx) : href;
  if (/^[a-z][a-z0-9+.-]*:/i.test(pathPart) || pathPart.startsWith('//')) return { external: true };
  if (!pathPart) return { path: '', fragment }; // pure in-page anchor, e.g. "#heading"
  const segments = basePath.split('/').slice(0, -1).concat(pathPart.split('/'));
  const resolved = [];
  for (const seg of segments) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') resolved.pop();
    else resolved.push(seg);
  }
  return { path: resolved.join('/'), fragment };
}

function _scrollMarkdownPanelToFragment(name, fragment) {
  const panel = _openMarkdownPanels.get(name);
  const target = panel && panel.querySelector('#' + CSS.escape(fragment));
  if (target) target.scrollIntoView({ block: 'start' });
}

// `fragment`, when given, scrolls to that heading's slug id (see parseMarkdown()'s heading
// handling) once the panel's content is actually in the DOM — including when the target was
// already open, which previously just no-opped here (fine for its only other caller,
// showMarkdownMenu(), which routes an already-open entry to closeMarkdownPanel() instead — this
// path is only reached for a fresh open there) but would otherwise leave a same-doc link (e.g. a
// table of contents entry) unable to raise/rescroll an already-open panel.
async function openMarkdownFile(name, fragment) {
  if (_openMarkdownPanels.has(name)) {
    _bringMarkdownPanelToFront(name);
    if (fragment) _scrollMarkdownPanelToFragment(name, fragment);
    return;
  }
  const panel = document.createElement('div');
  panel.className = 'markdown-panel';
  panel.dataset.mdPath = name; // read by the doc-link click handler below to resolve relative hrefs
  panel.innerHTML =
    '<div class="markdown-panel-header"><span></span>' +
    '<button class="icon-btn" data-tooltip="Close">✕</button></div>' +
    '<div class="markdown-content">Loading…</div>';
  panel.querySelector('span').textContent = name;
  const closeBtn = panel.querySelector('.icon-btn');
  closeBtn.onclick = () => closeMarkdownPanel(name);
  _wireHoverTooltip(closeBtn, 'Close');
  // Clicking anywhere on a panel (background or front) raises it, same as clicking a background
  // window — except the close button itself, which should just close it.
  panel.addEventListener('mousedown', e => {
    if (!e.target.closest('.icon-btn')) _bringMarkdownPanelToFront(name);
  });
  document.getElementById('markdown-panels').appendChild(panel);
  _openMarkdownPanels.set(name, panel);
  _layoutMarkdownPanels();
  _persistOpenMarkdownDocs();

  let content;
  try {
    const res = await apiFetch('/plugin/documents/content?name=' + encodeURIComponent(name));
    const data = await res.json();
    content = data.content || '';
  } catch (e) {
    content = '(failed to load)';
  }
  panel.querySelector('.markdown-content').innerHTML = parseMarkdown(content);
  if (fragment) _scrollMarkdownPanelToFragment(name, fragment);
}

// One delegated listener covers every panel, including ones opened after this runs — a link
// inside rendered markdown is otherwise just an ordinary <a href>, which would navigate this
// whole SPA tab away (losing in-memory state) to a URL nothing here serves (NIXOS_TARGET's *.md
// files are only ever reachable through /api/v1/markdown-files/content, not as static paths).
// Only a relative link that resolves to another file _markdownFiles actually lists is turned into
// an in-app panel open; anything else (external, or a relative link to something that isn't a
// known .md file) is left to inline()'s own target="_blank" fallback rather than guessed at, since
// there's no general file-serving endpoint to open it against anyway.
document.getElementById('markdown-panels').addEventListener('click', e => {
  const a = e.target.closest('a');
  if (!a) return;
  const panel = a.closest('.markdown-panel');
  const basePath = panel ? panel.dataset.mdPath : '';
  const resolved = _resolveMdLink(basePath, a.getAttribute('href') || '');
  if (resolved.external) return; // let target="_blank" open it normally
  e.preventDefault();
  if (!resolved.path) {
    // Same-document heading link (e.g. "#setup") -- scrolled explicitly within this panel rather
    // than left to native anchor navigation, which isn't scoped to a panel and could land on a
    // same-slugged heading in a *different* currently-open document instead.
    if (resolved.fragment) _scrollMarkdownPanelToFragment(basePath, resolved.fragment);
    return;
  }
  if (!_markdownFiles.includes(resolved.path)) {
    setStatus('Linked file not found: ' + resolved.path, 3000, 'err');
    return;
  }
  openMarkdownFile(resolved.path, resolved.fragment || undefined);
});

function closeMarkdownPanel(name) {
  const panel = _openMarkdownPanels.get(name);
  if (!panel) return;
  panel.remove();
  _openMarkdownPanels.delete(name);
  _layoutMarkdownPanels();
  _persistOpenMarkdownDocs();
}

eznix.on('ready', initMarkdownMenu);
