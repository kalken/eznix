// nixedit: the fields that hold a Nix expression (.expr-input, .expr-value) edited as in a
// text editor: completion and indenting. Without this plugin they are plain text fields. It
// reaches the page through nothing but listeners on the document and what the page has in its
// scope (packages, optionSearch(), findOption(), choicesFor(), parseEnumOptions(), typeFromNix(),
// _floatPopup(), _escHtml(), _showFieldTooltip(), _hideFieldTooltip()); the page tells
// each field the path of the option it is (_exprPath) and knows nothing of this file.

// Completion in any field that holds a Nix expression (.expr-input, .expr-value), wherever it
// is drawn (the user's wish, 2026-10-27: package names and the like, not an editor that knows
// Nix). Three things are completed. A dotted name before the cursor that starts with a name
// there is a list for (_EXPR_NAMES): `pkgs.` the packages, `config.` the options. A value, from
// what the option can be chosen from (_exprValuesFor()). And the name of a setting where one is
// written in a set: the field knows its own path (_exprPath, set where it
// is drawn), and _exprBindingAt() follows the sets and lists before the cursor
// (`a = { b = [ { ` is a.b.*), so a section turned into an expression completes the options
// under it, at every depth. Nothing more of Nix is read: `let`, `with` and a function's
// arguments are not known, and a string's `${ }` is skipped whole. Up and Down choose, Enter
// takes the one chosen and Tab the first if none is, Escape closes, moving the cursor closes; taking puts the name in place of what was typed of it and goes
// through the field's own 'input' so it is stored as any typing is.
const _EXPR_NAMES = {
  pkgs: rest => packages.filter(p => p.name.toLowerCase().startsWith(rest.toLowerCase()))
    .slice(0, 50).map(p => ({ name: p.name, label: 'pkgs.' + p.name, desc: p.description })),
  config: rest => optionSearch(rest).map(o => ({ name: o.displayPath, label: 'config.' + o.displayPath, desc: o.description })),
};
// Where in the sets the end of `text` is. { path, typed } where a setting's name is written
// (the start of a binding, after `{` or `;`): path the names of the sets around it from the
// expression's own value down, typed what is written of the name so far. { value, path, typed,
// quoted } where a value is written: path that of the setting it is the value of (a list's own
// for an entry of it, [] for the expression itself), typed what is written of it, quoted when
// inside a string just opened. null in a comment, a string with `${` or anywhere else.
function _exprBindingAt(text) {
  const frames = [{ open: '', path: [] }];
  let stmt = '';
  const bound = () => {
    const m = stmt.match(/^\s*((?:[\w'-]+|"[^"]*")(?:\s*\.\s*(?:[\w'-]+|"[^"]*"))*)\s*=(?!=)/);
    return m ? _pathParts(m[1].replace(/\s+/g, '')) : null;
  };
  // Whose value is written here: in a set the binding's, in a list the list's, at the top the
  // expression's own unless it binds something (`let`, say).
  const owner = () => {
    const top = frames[frames.length - 1];
    if (top.open === '[') return top.path;
    const name = bound();
    if (top.open === '{') return name ? [...top.path, ...name] : null;
    return name ? null : top.path;
  };
  for (let i = 0; i < text.length;) {
    const c = text[i], top = frames[frames.length - 1];
    if (c === '#') { const j = text.indexOf('\n', i); if (j < 0) return null; i = j; continue; }
    if (c === '/' && text[i + 1] === '*') { const j = text.indexOf('*/', i + 2); if (j < 0) return null; i = j + 2; continue; }
    if (c === '"') {
      let j = i + 1;
      while (j < text.length && text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
      if (j >= text.length) {
        const typed = text.slice(i + 1), path = owner();
        return path && !/[\\$]/.test(typed) ? { value: true, path, typed, quoted: true } : null;
      }
      stmt += text.slice(i, j + 1); i = j + 1; continue;
    }
    if (c === "'" && text[i + 1] === "'") { const j = text.indexOf("''", i + 2); if (j < 0) return null; stmt += "''"; i = j + 2; continue; }
    if (c === '{' || c === '[') {
      const name = top.open !== '[' && bound();
      frames.push({ open: c, path: name ? [...top.path, ...name] : top.open === '[' ? [...top.path, '*'] : top.path });
      stmt = '';
    } else if (c === '}' || c === ']') {
      if (frames.length > 1) frames.pop();
      stmt = '';
    } else if (c === ';') stmt = '';
    else stmt += c;
    i++;
  }
  const top = frames[frames.length - 1];
  const m = stmt.match(/^\s*((?:[\w'-]+\.)*[\w'-]*)$/);
  if (top.open === '{' && m) return { path: top.path, typed: m[1] };
  const path = owner();
  return path ? { value: true, path, typed: stmt.match(/[\w'.-]*$/)[0], quoted: false } : null;
}
// What a value can be chosen from: the option's values in choices.json (what the generator's
// plugins make: Homebrew's names, the kernels) or the ones its type lists ("one of ..."), as
// the page's dropdowns and chips offer them. The option is the value's path with the entry of a
// list taken off (a list's values are its entries').
function _exprValuesFor(path) {
  const p = path.map(String);
  while (p.length && (p[p.length - 1] === '*' || /^\d+$/.test(p[p.length - 1]))) p.pop();
  if (!p.length) return null;
  const c = choicesFor(p);
  if (c) return { expr: !!c.expr, items: c._items.map(i => ({ value: i.value, desc: i.description })) };
  const opt = findOption(p);
  const en = opt && parseEnumOptions(opt.type);
  return en ? { expr: false, items: en.values.map(v => ({ value: v })) } : null;
}
// Only once something of the name's last part is typed (the user, 2026-10-27: nothing shows
// unless typed), or when asked for with Ctrl+Space.
function _exprCompletions(field, asked) {
  const before = field.value.slice(0, field.selectionStart);
  const lastPart = t => t.slice(t.lastIndexOf('.') + 1);
  const m = before.match(/(?:^|[^\w'.-])([A-Za-z_][\w'-]*)\.([\w'.-]*)$/);
  const at = field._exprPath ? _exprBindingAt(before) : null;
  // A value the option has choices for takes them, also where they are `pkgs.` expressions (the
  // kernels); anywhere else a `pkgs.` or `config.` outside a string is the whole list.
  const vals = at && at.value ? _exprValuesFor([...field._exprPath, ...at.path]) : null;
  if (m && Object.hasOwn(_EXPR_NAMES, m[1]) && !(at && at.quoted) && !vals) {
    if (!asked && !lastPart(m[2])) return null;
    return { start: before.length - m[2].length, items: _EXPR_NAMES[m[1]](m[2]).filter(i => i.name !== m[2]) };
  }
  if (!at || (!asked && !lastPart(at.typed))) return null;
  if (at.value) {
    // A value: one of the option's, in quotes unless they are expressions, the closing quote
    // put in when it is not there (_exprACTake()).
    if (!vals || (at.quoted && vals.expr)) return null;
    const t = at.typed.toLowerCase();
    const items = vals.items.filter(i => i.value.toLowerCase().startsWith(t) && i.value !== at.typed).slice(0, 50)
      .map(i => ({ name: i.value, label: i.value, desc: i.desc, quote: !vals.expr && !at.quoted, close: at.quoted }));
    return { start: before.length - at.typed.length, items };
  }
  const q = p => p === '' || /[."]/.test(p) ? '"' + p + '"' : p;
  const prefix = [...field._exprPath, ...at.path].map(String);
  const head = prefix.join('.') + '.';
  const seen = new Set();
  const items = [];
  for (const o of optionSearch([...prefix.map(q), at.typed].join('.'))) {
    if (!o.displayPath.startsWith(head)) continue;
    const name = o.displayPath.slice(head.length);
    if (name === at.typed || seen.has(name)) continue;
    seen.add(name);
    items.push({ name, label: name, desc: o.description, type: o.type, binding: true });
  }
  return { start: before.length - at.typed.length, items };
}
const _exprAC = { list: null, field: null, start: 0, items: [], idx: -1, quiet: false };
function _exprACHide() {
  if (_exprAC.list) _exprAC.list.classList.add('hidden');
  _exprAC.field = null; _exprAC.items = []; _exprAC.idx = -1;
}
function _exprACShow(field, asked) {
  const found = _exprCompletions(field, asked);
  if (!found || !found.items.length) { _exprACHide(); return; }
  if (!_exprAC.list) {
    _exprAC.list = document.createElement('div');
    _exprAC.list.className = 'autocomplete-list expr-ac hidden';
    document.body.appendChild(_exprAC.list);
  }
  Object.assign(_exprAC, { field, start: found.start, items: found.items, idx: -1 });
  const list = _exprAC.list;
  list.innerHTML = '';
  found.items.forEach((it, i) => {
    const el = document.createElement('div');
    el.className = 'autocomplete-item';
    el.innerHTML = `<span class="ac-name">${_escHtml(it.label)}</span>` +
      (it.desc ? `<span class="ac-desc">${_escHtml(String(it.desc).split('\n')[0])}</span>` : '');
    el.addEventListener('mousedown', e => { e.preventDefault(); _exprACTake(i); });
    list.appendChild(el);
  });
  list.classList.remove('hidden');
  // Under the word being completed, as a text editor puts it, not under the whole field; its
  // text in the column of the word's (the item's padding and the list's border to the left).
  const start = found.start;
  _floatPopup(list, {
    get isConnected() { return field.isConnected; },
    getBoundingClientRect() {
      const r = _caretRect(field, start);
      return { left: r.left - 9, top: r.top, bottom: r.bottom, width: 0 };
    },
  });
}
// Where in the window the character at `pos` of a text field is drawn: a copy of the field's
// text up to there, in the field's font, width and padding, measured and thrown away, less
// what the field has scrolled.
// A copy of a text field's text box, unseen, laid over the field where its text is drawn (less
// what the field has scrolled), so that what is put in it lands where the field draws the same
// text: how a place in the text is found on screen and the other way round.
function _mirrorOf(field) {
  const cs = getComputedStyle(field);
  const m = document.createElement('div');
  for (const p of ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing', 'lineHeight',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'tabSize', 'textIndent', 'wordBreak']) m.style[p] = cs[p];
  const r = field.getBoundingClientRect();
  Object.assign(m.style, {
    position: 'fixed', visibility: 'hidden', border: '0', boxSizing: 'border-box', pointerEvents: 'none',
    left: (r.left + field.clientLeft - field.scrollLeft) + 'px', top: (r.top + field.clientTop - field.scrollTop) + 'px',
    width: field.clientWidth + 'px', overflowWrap: cs.overflowWrap,
    whiteSpace: field instanceof HTMLTextAreaElement && cs.whiteSpace !== 'nowrap' ? 'pre-wrap' : 'pre',
  });
  return m;
}
// Where in the window the character at `pos` of a text field is drawn.
function _caretRect(field, pos) {
  const m = _mirrorOf(field);
  m.textContent = field.value.slice(0, pos);
  const mark = document.createElement('span');
  mark.textContent = '​';
  m.appendChild(mark);
  document.body.appendChild(m);
  const r = mark.getBoundingClientRect();
  m.remove();
  return { left: r.left, top: r.top, bottom: r.bottom };
}
function _exprACTake(i) {
  const { field, start, items } = _exprAC;
  if (!field || !items[i]) return;
  const it = items[i], end = field.selectionStart;
  let text = it.quote ? '"' + it.name + '"' : it.name, cursor = text.length;
  if (it.close && field.value[end] !== '"') text += '"';
  if (it.close) cursor = text.length;
  // A setting's name written in a set is written out up to its value, which is left to type:
  // ` = "|";` for a text, ` = [ | ];` a list, a set opened on a line of its own, ` = |;` the rest,
  // by the kind the option's type is (typeFromNix(), as Add option reads it). Not when a `=`
  // follows already. (The user's wish, 2026-10-27: "autocompletes all the way until i need to
  // edit".)
  if (it.binding && !/^\s*=/.test(field.value.slice(end))) {
    const v = field.value, ls = v.lastIndexOf('\n', start - 1) + 1;
    const indent = v.slice(ls).match(/^[ \t]*/)[0];
    const kind = typeFromNix(it.type);
    const [open, close] = kind === 'string' ? ['"', '"']
      : kind === 'array' ? ['[ ', ' ]']
      : kind === 'object' ? (field instanceof HTMLTextAreaElement ? ['{\n' + indent + '  ', '\n' + indent + '}'] : ['{ ', ' }'])
      : ['', ''];
    text += ' = ' + open;
    cursor = text.length;
    text += close + ';';
  }
  _exprACHide();
  // Stored by the field's own handler; the list stays closed until the next key typed.
  _exprAC.quiet = true;
  _insertInField(field, text, start, end);
  _exprAC.quiet = false;
  field.selectionStart = field.selectionEnd = start + cursor;
}
function _isExprField(t) {
  return (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) &&
    (t.classList.contains('expr-input') || t.classList.contains('expr-value'));
}
document.addEventListener('input', e => { if (_isExprField(e.target) && !_exprAC.quiet) _exprACShow(e.target); }, true);
// Before the field's own keys (Enter in a list's item adds an item): capture, on the document.
document.addEventListener('keydown', e => {
  if (e.key === ' ' && e.ctrlKey && !e.altKey && !e.metaKey && _isExprField(e.target)) {
    e.preventDefault(); _exprACShow(e.target, true); return;
  }
  if (e.target !== _exprAC.field || !_exprAC.items.length || e.isComposing) return;
  const n = _exprAC.items.length;
  // Moving the cursor away, or Up with nothing chosen, closes the list and moves as ever, so
  // the list never holds the cursor in place.
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key) ||
      (e.key === 'ArrowUp' && _exprAC.idx < 0)) { _exprACHide(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    _exprAC.idx = e.key === 'ArrowDown' ? Math.min(_exprAC.idx + 1, n - 1) : Math.max(_exprAC.idx - 1, -1);
    const els = _exprAC.list.children;
    for (let i = 0; i < els.length; i++) els[i].classList.toggle('active', i === _exprAC.idx);
    if (_exprAC.idx >= 0) els[_exprAC.idx].scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Tab' || (e.key === 'Enter' && _exprAC.idx >= 0)) {
    _exprACTake(Math.max(_exprAC.idx, 0));
  } else if (e.key === 'Escape') {
    _exprACHide();
  } else return;
  e.preventDefault(); e.stopImmediatePropagation();
}, true);
document.addEventListener('focusout', e => { if (e.target === _exprAC.field) _exprACHide(); }, true);
document.addEventListener('mousedown', e => { if (e.target === _exprAC.field) _exprACHide(); }, true);

// Help on hovering a name in an expression (the user's wish, 2026-10-27): after the pause the
// page's own tooltips have, the tooltip of the whole name under the pointer, wherever on it
// (the user's wish: it was the part pointed at, and only the last part of a name is ever an
// option): an option (`config.a.b`, or a setting written in a set, by the same reading as
// the completion) or a package (`pkgs.x`). Nothing for anything else. Through the page's
// _showFieldTooltip(), anchored to the name's box.
function _nameAt(field, x, y) {
  const m = _mirrorOf(field);
  const v = field.value, re = /[A-Za-z_][\w'-]*(?:\.[A-Za-z_][\w'-]*)*/g;
  const spans = [];
  let last = 0, t;
  while ((t = re.exec(v))) {
    m.appendChild(document.createTextNode(v.slice(last, t.index)));
    const sp = document.createElement('span');
    sp.textContent = t[0];
    m.appendChild(sp);
    spans.push({ sp, start: t.index, word: t[0] });
    last = t.index + t[0].length;
  }
  m.appendChild(document.createTextNode(v.slice(last)));
  document.body.appendChild(m);
  let hit = null;
  for (const s of spans) {
    const r = s.sp.getBoundingClientRect();
    if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) { hit = { ...s, rect: r }; break; }
  }
  m.remove();
  return hit;
}
function _helpFor(field, hit) {
  const parts = hit.word.split('.');
  if (parts[0] === 'pkgs' && parts.length === 2) {
    const p = packages.find(p => p.name === parts[1]);
    return p ? { description: p.description, type: 'package' } : null;
  }
  if (parts[0] === 'config' && parts.length > 1) return findOption(parts.slice(1));
  const at = field._exprPath && _exprBindingAt(field.value.slice(0, hit.start));
  if (!at || at.value) return null;
  return findOption([...field._exprPath, ...at.path, ...parts].map(String));
}
let _helpTimer = null, _helpShown = null;
function _helpHide() {
  clearTimeout(_helpTimer); _helpTimer = null;
  if (_helpShown) { _hideFieldTooltip(); _helpShown = null; }
}
document.addEventListener('mousemove', e => {
  const f = e.target;
  if (!_isExprField(f)) { if (_helpTimer || _helpShown) _helpHide(); return; }
  if (_helpShown) {
    const r = _helpShown;
    if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) return;
    _helpHide();
  }
  clearTimeout(_helpTimer);
  const x = e.clientX, y = e.clientY;
  _helpTimer = setTimeout(() => {
    _helpTimer = null;
    if (_exprAC.field === f || !f.isConnected) return;
    const hit = _nameAt(f, x, y);
    const opt = hit && _helpFor(f, hit);
    if (!opt) return;
    _showFieldTooltip({ getBoundingClientRect: () => hit.rect }, opt);
    _helpShown = hit.rect;
  }, 1000);
}, true);
for (const ev of ['mousedown', 'keydown', 'scroll']) document.addEventListener(ev, () => { if (_helpTimer || _helpShown) _helpHide(); }, true);
document.addEventListener('mouseout', e => { if (_isExprField(e.target) && !(e.relatedTarget && e.target.contains(e.relatedTarget))) _helpHide(); }, true);

// Indenting in a Nix expression that spans lines (.expr-input), as a text editor does (the
// user's wish, 2026-10-27): Enter starts the new line at the indent of the one it breaks, a step
// (two spaces, as jsonToNix() writes) further after an opening `{`, `[`, `(` or a `=` at the
// line's end, and between a bracket and its partner (`{|}`) the partner goes on a line of its
// own; a closing bracket typed where only spaces stand before it on its line takes a step back.
// Through insertText, so the browser's own undo has it and the field's 'input' stores it.
// After the completion's keys, which take an Enter that chooses.
function _insertInField(field, text, from, to) {
  field.setSelectionRange(from, to);
  if (!document.execCommand('insertText', false, text)) {
    field.setRangeText(text, from, to, 'end');
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }
}
document.addEventListener('keydown', e => {
  const f = e.target;
  if (!(f instanceof HTMLTextAreaElement) || !_isExprField(f) || e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
  const pos = f.selectionStart, v = f.value;
  const lineStart = v.lastIndexOf('\n', pos - 1) + 1;
  const indent = v.slice(lineStart).match(/^[ \t]*/)[0];
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const before = v.slice(lineStart, pos).trimEnd(), after = v.slice(f.selectionEnd);
    const opens = /[{[(=]$/.test(before);
    const inner = opens ? indent + '  ' : indent;
    const pair = { '{': '}', '[': ']', '(': ')' }[before.slice(-1)];
    const closes = pair && after.trimStart().startsWith(pair);
    _insertInField(f, '\n' + inner + (closes ? '\n' + indent : ''), pos, closes ? pos + (after.length - after.trimStart().length) : f.selectionEnd);
    if (closes) f.selectionStart = f.selectionEnd = pos + 1 + inner.length;
  } else if ('}])'.includes(e.key) && e.key.length === 1 && pos === f.selectionEnd && /^[ \t]+$/.test(v.slice(lineStart, pos))) {
    e.preventDefault();
    const back = v.slice(lineStart, pos).replace(/(?: {1,2}|\t)$/, '');
    _insertInField(f, back + e.key, lineStart, pos);
  }
}, true);
