// The documents plugin: a "Documents" button in the header listing every *.md file in the
// flake, each opening as a panel on the side (eznix.sidePanel()). documents.py in this folder
// lists and reads the files; everything else is here.
// In the header beside Backup/Restore/Import/Export, with an icon like theirs (a page with
// lines, Lucide's "file-text") and its name, which the user asked to keep beside the icon. It was a button reading "Documents" at the end of the tab bar until
// 2026-10, when the user wanted it on the row with those.
const _mdMenuBtn = eznix.addButton('header', {
  id: 'md-menu-btn', tooltip: 'Browse .md files in the flake',
  html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>Documents',
  onclick: e => showMarkdownMenu(e),
});
_mdMenuBtn.classList.add('hidden');

// Minimal Markdown → HTML parser, no dependencies — ported from github.com/kalken/ezblog's
// app.js (same zero-dependency philosophy as this project). Raw HTML in the source is shown as
// text, and a link or an image takes only http(s), mailto and addresses without a scheme
// (2026-10-16). It passed through as written before, on the thought that these files are the
// flake's own; but a flake takes files from elsewhere (a zip imported, a repository cloned),
// and a script in this page can use the whole API and the terminal, which is a shell as the
// user. Run on `<img src=x onerror=...>` and `[x](javascript:...)`, outside the browser.
function parseMarkdown(text) {
  const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Stash fenced code blocks before any other processing
  const stash = [];
  const stashPush = s => { stash.push(s); return `\x02${stash.length - 1}\x03`; };
  const stashPop = s => s.replace(/\x02(\d+)\x03/g, (_, i) => stash[+i]);

  text = text.replace(/^```(\w*)\n([\s\S]*?)^```/gm, (_, lang, code) =>
    stashPush(`<pre><code${lang ? ` class="language-${lang}"` : ''}>${escape(code.trimEnd())}</code></pre>`)
  );

  // An address in a link or an image: no scheme at all, or http, https or mailto. Control
  // characters and spaces are dropped first (a browser ignores a tab inside "java\tscript:"),
  // and & and " are escaped so that an entity cannot spell what was just refused.
  const safeUrl = u => {
    u = u.replace(/[\x00-\x20\x7f]/g, '');
    if (/^[a-z][a-z0-9+.-]*:/i.test(u) && !/^(https?|mailto):/i.test(u)) return '#';
    return u.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  };
  const attr = s => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

  function inline(s) {
    // Code spans first, and set aside: what is inside them is escaped once, below, and what is
    // outside has its "<" escaped so that no tag is ever written by the source.
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (_, c) => `\x04${codes.push(escape(c)) - 1}\x05`);
    s = s.replace(/</g, '&lt;');
    return stashPop(s
      // target="_blank" on every link (both here and the text-link replace below) is what keeps
      // a genuine external/unhandled link from navigating this SPA tab away to a dead URL
      // (nothing here serves arbitrary NIXOS_TARGET files, image links included) -- the doc-to-doc
      // case below is instead caught and preventDefault()-ed by a click handler before the
      // browser ever acts on href/target at all, so this is just the safe fallback for everything
      // that handler doesn't recognize as one of the open document's own siblings.
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => { const u = safeUrl(src.replace(/^\.\.\//, '')); return `<a href="${u}" target="_blank" rel="noopener noreferrer"><img alt="${attr(alt)}" src="${u}"></a>`; })
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => `<a href="${safeUrl(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`)
      .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
      .replace(/~~(.+?)~~/g, '<del>$1</del>')
      .replace(/\x04(\d+)\x05/g, (_, i) => `<code>${codes[+i]}</code>`)
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

    // One item of a list: its line without the marker, and with it the lines that follow
    // indented, which are the rest of a sentence that was broken to fit a width. Such a line
    // used to end the list, so the next item began a new one: a numbered list written that
    // way came out as 1, a paragraph, 1, 1, a paragraph (the user, 2026-10-13, on an
    // INSTALL.md: "a strange numbering on things"). An indented line that is itself the
    // start of something (an item of a list inside this one, a code block) is left alone.
    const takeItem = marker => {
      let text = lines[i++].replace(marker, '');
      while (i < lines.length && /^\s+\S/.test(lines[i]) && !isBlock(lines[i].trim())) text += ' ' + lines[i++].trim();
      return `<li>${inline(text)}</li>`;
    };

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) items.push(takeItem(/^[-*+]\s/));
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) items.push(takeItem(/^\d+\.\s/));
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
// Multiple files can be open at once, each in a panel of its own on the side: the page's
// stack (eznix.sidePanel()), which was this plugin's own until the Nix files needed the same
// place. _openMarkdownPanels maps an open file's name to its panel, doubling as "is this file
// currently open". Content is fetched fresh every time a panel is opened (openMarkdownFile()),
// not cached, so reopening a file after editing it on disk shows the current content.
let _markdownFiles = [];
const _openMarkdownPanels = new Map();
function _persistOpenMarkdownDocs() {
  localStorage.setItem('eznix-markdown-open', JSON.stringify([..._openMarkdownPanels.keys()]));
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
    clientX: rect.left, clientY: rect.bottom + 2, anchorRight: rect.right,   // the same gap the terminal bar's menus have: see _positionMenuAboveAnchor()
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
  const target = panel && panel.body.querySelector('#' + CSS.escape(fragment));
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
    _openMarkdownPanels.get(name).front();
    if (fragment) _scrollMarkdownPanelToFragment(name, fragment);
    return;
  }
  // Out of the way on a press outside the side, as the files' tabs and the terminal are,
  // unless switched off ([plugin.documents] auto_hide = false). The documents stayed put at
  // first, alone on the side; the user expected them to hide like the rest (2026-10-12).
  const panel = eznix.sidePanel({ group: 'documents', title: name,
    autoHide: (eznix.config.documents || {}).auto_hide !== false, onClose: () => { _openMarkdownPanels.delete(name); _persistOpenMarkdownDocs(); } });
  panel.body.classList.add('markdown-content');
  panel.body.dataset.mdPath = name; // read by the doc-link click handler below to resolve relative hrefs
  panel.body.textContent = 'Loading…';
  _openMarkdownPanels.set(name, panel);
  _persistOpenMarkdownDocs();

  let content;
  try {
    const res = await apiFetch('/plugin/documents/content?name=' + encodeURIComponent(name));
    const data = await res.json();
    content = data.content || '';
  } catch (e) {
    content = '(failed to load)';
  }
  panel.body.innerHTML = parseMarkdown(content);
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
document.addEventListener('click', e => {
  const a = e.target.closest && e.target.closest('.markdown-content a');
  if (!a) return;
  const basePath = a.closest('.markdown-content').dataset.mdPath || '';
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
  if (panel) panel.close();
}

eznix.on('ready', initMarkdownMenu);
