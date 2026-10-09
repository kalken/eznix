// The terminal's part of the page: the panel at the bottom, its command buttons, and the
// notice that the running terminal program is out of date. Part of eznix itself, not a plugin
// (a plugin needs nothing from the system; a terminal needs a process run for each user) --
// but kept out of index.html and loaded the way a plugin's files are, only when a terminal is
// set up (TERMINAL_PANEL in eznix.py), and talking to the page through the same events. So
// the page still never names anything in here. xterm.js and its addons are loaded before this.
const _TERM_CONFIG       = eznix.config.terminal || {};
const TERMINAL_AUTO_HIDE = _TERM_CONFIG.auto_hide !== false; // terminal_auto_hide in eznix.toml -- see initTerminalAutoHide()
const STATIC_BUTTONS     = _TERM_CONFIG.buttons || [];       // from [[buttons]] in eznix.toml — not tied to any tab

// The panel sits between the editor and the status bar. The restart notice is fixed to the
// right corner of the screen, right above wherever the terminal bar starts (bottom set fresh
// by _updateTermRestartPopup()): that edge is a constant screen position whatever the panel's
// size, while the panel's own top edge moves -- anchoring there made the notice jump.
document.querySelector('.statusbar').insertAdjacentHTML('beforebegin', `
<div class="term-restart-popup hidden" id="term-restart-popup" onclick="restartTerminal()">Terminal has changed - click to restart</div>

<div class="terminal-panel collapsed" id="terminal-panel">
  <div class="terminal-body">
    <div id="term-output"></div>
    <div class="term-status-banner hidden" id="term-status-banner"></div>
  </div>
  <div class="terminal-header-group">
    <div class="terminal-header">
      <div class="terminal-cmd-btns" id="terminal-cmd-btns"></div>
      <div class="terminal-header-actions">
        <button class="btn" id="term-restart-btn" data-tooltip="Restart terminal service" onclick="restartTerminal()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg></button>
        <button class="btn" data-tooltip="Quarter screen" onclick="setTerminalSize('quarter')"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="3" y="16" width="18" height="5" fill="currentColor" stroke="none"/></svg></button>
        <button class="btn" data-tooltip="Half screen" onclick="setTerminalSize('half')"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="3" y="12" width="18" height="9" fill="currentColor" stroke="none"/></svg></button>
        <button class="btn" data-tooltip="Full screen" onclick="setTerminalSize('full')"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="4" y="4" width="16" height="16" rx="1" fill="currentColor" stroke="none"/></svg></button>
        <button class="btn" id="term-toggle" data-tooltip="Show" onclick="toggleTerminal()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="18 15 12 9 6 15"/></svg></button>
      </div>
    </div>
    <div class="terminal-header hidden" id="terminal-header-install">
      <div class="terminal-cmd-btns" id="terminal-cmd-btns-install"></div>
    </div>
  </div>
</div>
`);

function _buildTermTheme() {
  const css = getComputedStyle(document.documentElement);
  const tv = k => css.getPropertyValue(k).trim();
  const theme = {};
  for (const [v, k] of [
    ['--term-bg','background'], ['--term-fg','foreground'],
    ['--term-cursor','cursor'], ['--term-selection','selectionBackground'],
    ['--term-black','black'], ['--term-red','red'],
    ['--term-green','green'], ['--term-yellow','yellow'],
    ['--term-blue','blue'], ['--term-magenta','magenta'],
    ['--term-cyan','cyan'], ['--term-white','white'],
    ['--term-bright-black','brightBlack'], ['--term-bright-red','brightRed'],
    ['--term-bright-green','brightGreen'], ['--term-bright-yellow','brightYellow'],
    ['--term-bright-blue','brightBlue'], ['--term-bright-magenta','brightMagenta'],
    ['--term-bright-cyan','brightCyan'], ['--term-bright-white','brightWhite'],
  ]) { const val = tv(v); if (val) theme[k] = val; }
  return theme;
}

// ── Terminal panel ─────────────────────────────────────────────────────────────
let _term = null;
let _termWs = null;
let _termFit = null;
let _termOnData = null;
let _termReconnectTimer = null;
let _termReconnectAttempts = 0;
// Set once the server's {"type":"ready"} control message arrives for the current connection
// (see connectTerminalWs()'s onmessage) -- waiting for this instead of guessing readiness from
// the WebSocket's own open state or the first byte received avoids sending input before the
// shell on the other end is actually ready to receive it, which could otherwise
// silently go nowhere. _termReadyWaiters holds callbacks queued by _waitTermReady() while not
// yet ready; both reset at the top of every connectTerminalWs() call (a fresh connection is
// never ready yet, and stale waiters from an abandoned connection would never fire otherwise).
let _termReady = false;
let _termReadyWaiters = [];
// Set only by the server's {"type":"exited"} control message (see bin/eznix-terminal.py's
// _session_reader()) -- the one signal that actually means the shell process itself is gone, as
// opposed to just a dropped/closed connection (network blip, browser closed, logout) while the
// shell keeps running server-side. onclose below branches on this, not on the WebSocket's own
// wasClean, since wasClean reflects whether the *connection* closed cleanly, not whether the
// *shell* did -- those are different events entirely under session persistence. Reset at the top
// of every connectTerminalWs() call.
let _termExited = false;

// Is the terminal that is running another one than is installed and configured now? The server
// works that out (_terminal_stale() in eznix.py) and says so in every /api/v1/ping, so this is
// right whether or not the panel is open, and after a reload. It drives #term-restart-popup, see
// _updateTermRestartPopup(), and is not sticky: it clears itself with the first ping after the
// two agree again, however that came about (this button, a restart from a shell over SSH).
let _terminalStale = false;
function _terminalNeedsRestart() { return _terminalStale; }
// Positioned fresh every time it's shown -- see the markup comment above #term-restart-popup for
// why this is anchored to the terminal bar's own top edge rather than any specific button.
function _updateTermRestartPopup() {
  const popup = document.getElementById('term-restart-popup');
  if (!_terminalNeedsRestart()) { popup.classList.add('hidden'); return; }
  popup.classList.remove('hidden');
  // Right corner of the screen (fixed in CSS -- see .term-restart-popup) rather than anchored to
  // any one button, so it isn't tied to that button's own width/label/icon at all -- just
  // #terminal-header-group's own top edge (both rows, in install mode, not just the first),
  // which is a constant screen position regardless of the panel's quarter/half/full/collapsed
  // size: .terminal-header-group is pinned to the panel's bottom via position: absolute;
  // bottom: 0 (see "Terminal panel" below), and the panel's own bottom edge never moves either
  // (it's a normal flex item sitting right above the statusbar -- growing its height only pushes
  // its *top* edge up into .layout above it). window.innerHeight - top, not top itself, since
  // bottom-anchoring the popup means its own height never has to be measured here at all.
  const barTop = document.querySelector('.terminal-header-group').getBoundingClientRect().top;
  popup.style.bottom = (window.innerHeight - barTop + 1) + 'px';
}
// The one restart mechanism now -- runs systemctl directly from eznix.py's own process (see
// POST /api/v1/terminal/restart there) rather than typing the command into the terminal's own
// shell, so it works even if that shell is wedged or the panel's never been opened. Restarting
// ends every running shell for everyone connected; there's no "clean" state that makes that safe
// to do silently, so this stays a manual click always, whether triggered from the plain button or
// from #term-restart-popup sitting above it. The popup itself doesn't need to be told this ran --
// it clears on its own, via the same reactive hash comparison, once the next ping/WS 'ready'
// after the real restart reports matching hashes.
async function restartTerminal() {
  const btn = document.getElementById('term-restart-btn');
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    const res = await apiFetch('/terminal/restart', { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setStatus('Terminal service restarted', 3000, 'ok');
      // Take the notice down now and not with the next ping, up to five seconds on; that ping
      // puts it back if the restart didn't bring up the right terminal after all.
      _terminalStale = false;
      _updateTermRestartPopup();
    } else {
      setStatus('Restart failed: ' + (data.error || res.status), 5000, 'err');
    }
  } catch (e) {
    setStatus('Restart failed: ' + e.message, 4000, 'err');
  } finally {
    btn.disabled = false;
  }
}

function _waitTermReady() {
  if (_termReady) return Promise.resolve();
  return new Promise(resolve => _termReadyWaiters.push(resolve));
}

// Same origin as the page itself (eznix.py proxies this through to eznix-terminal.py over loopback,
// see _proxy_terminal() in eznix.py) -- not a separate host:port, which would be a different
// origin needing its own certificate-trust decision the browser has no way to prompt for over a
// raw WebSocket handshake.
const _TERM_WS_BASE = (() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/terminal`;
})();

async function initTerminal() {
  if (_term) return;
  const container = document.getElementById('term-output');
  if (!container) return;
  try {
    const _termTheme = _buildTermTheme();
    const _css = getComputedStyle(document.documentElement);
    const _tv = k => _css.getPropertyValue(k).trim();
    const _cursorStyle = _tv('--term-cursor-style');
    const _cursorBlink = _tv('--term-cursor-blink');
    const _cursorInactiveStyle = _tv('--term-cursor-inactive-style');
    _term = new Terminal({
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Hack', ui-monospace, monospace",
      fontWeight: '400',
      fontWeightBold: '600',
      lineHeight: 1.2,
      letterSpacing: 0.5,
      cursorStyle: _cursorStyle || 'bar',
      cursorInactiveStyle: _cursorInactiveStyle || 'none',
      ...(_cursorBlink !== '' && { cursorBlink: _cursorBlink === '1' || _cursorBlink === 'true' }),
      convertEol: true,
      scrollback: 5000,
      // xterm.js's own bypass for forcing native (browser) selection instead of reporting the
      // drag as a mouse event to the program -- Shift+drag on Windows/Linux, but on macOS it's
      // Option+drag *and* only if this is explicitly turned on (matching the same Option-click
      // convention Terminal.app/iTerm use). Useful whenever something inside the shell turns on
      // its own mouse tracking (vim, htop, etc.), which would otherwise swallow a plain drag.
      macOptionClickForcesSelection: true,
      ...(Object.keys(_termTheme).length && { theme: _termTheme }),
    });
    _termFit = new FitAddon.FitAddon();
    _term.loadAddon(_termFit);
    try {
      const webgl = new WebglAddon.WebglAddon();
      webgl.onContextLoss(() => webgl.dispose());
      _term.loadAddon(webgl);
    } catch (_) {}
    _term.open(container);
    _termFit.fit();
    let _fitTimer = null;
    new ResizeObserver(() => {
      clearTimeout(_fitTimer);
      _fitTimer = setTimeout(() => {
        if (_termFit) _termFit.fit();
      }, 200);
    }).observe(container);
    _term.onResize(({ cols, rows }) => {
      if (_termWs && _termWs.readyState === WebSocket.OPEN)
        _termWs.send(JSON.stringify({ type: 'resize', cols, rows }));
    });
    _term.attachCustomKeyEventHandler((e) => {
      if (e.type !== 'keydown') return true;
      // Ctrl+C copies the current selection instead of sending SIGINT, matching the convention
      // most web terminals (VS Code's integrated terminal included) use -- xterm.js doesn't do
      // this itself, it always sends the literal control byte otherwise, which would make a
      // just-made selection impossible to actually copy via the key everyone reaches for. Not
      // Cmd+C: that's the browser's own native copy shortcut and isn't intercepted by xterm.js
      // in the first place, so it already works with no help needed here.
      if (e.ctrlKey && !e.metaKey && (e.key === 'c' || e.key === 'C') && _term.hasSelection()) {
        e.preventDefault();
        navigator.clipboard?.writeText(_term.getSelection()).catch(() => {});
        return false;
      }
      return true;
    });
    connectTerminalWs();
  } catch (e) {
    console.error('Terminal init failed:', e);
  }
}

// NixOS-snowflake icon markup, used by the terminal reconnect banner below (spinning while it
// reconnects). The icon is the NixOS snowflake (nix-snowflake-colours.svg from
// github.com/NixOS/nixos-artwork, CC-BY-SA), pared down to just its drawable geometry -- one
// path (plus its own mirrored twin) repeated via <use> at 60deg rotations, keeping the original
// coordinates/transforms as-is so re-checking against the source stays straightforward. Filled
// with currentColor rather than the source artwork's own two-tone blue gradients, matching every
// other icon in the app (all stroke="currentColor"), so it inherits the button's own theme color
// instead of a fixed brand color that clashes against a dark/light/gruvbox button background.
// .nixos-spinner's own size (style.css) is what each call site scales it to -- the markup itself
// is size-agnostic; the "spin" class is what actually animates it (see @keyframes nixos-spin).
function _nixosLogoSvg(spinning = false) {
  return `<svg class="nixos-spinner${spinning ? ' spin' : ''}" viewBox="0 0 501.56251 501.56249" aria-hidden="true">
  <g transform="translate(-156.41121,933.30685)">
    <g transform="matrix(0.99994059,0,0,0.99994059,-0.06321798,33.188377)">
      <path id="ns-p1" fill="currentColor" d="m 309.54892,-710.38827 122.19683,211.67512 -56.15706,0.5268 -32.6236,-56.8692 -32.85645,56.5653 -27.90237,-0.011 -14.29086,-24.6896 46.81047,-80.4901 -33.22946,-57.8257 z"/>
      <use href="#ns-p1" transform="rotate(60,407.11155,-715.78724)"/>
      <use href="#ns-p1" transform="rotate(-60,407.31177,-715.70016)"/>
      <use href="#ns-p1" transform="rotate(180,407.41868,-715.7565)"/>
      <use href="#ns-p1" transform="rotate(120,407.33916,-716.08356)"/>
      <use href="#ns-p1" transform="rotate(-120,407.28823,-715.86995)"/>
    </g>
  </g>
</svg>`;
}

// A fixed overlay rather than writing status into the terminal's own scrolling buffer (what this
// replaced) -- each failed reconnect attempt writing its own line there pushed the previous one
// out of view almost immediately on a short panel, reading as flicker rather than one steady
// message. A separate DOM element isn't touched by that at all, and stays visible continuously
// across attempts instead. null hides it.
function _setTermStatusBanner(text, spinning = false) {
  const el = document.getElementById('term-status-banner');
  if (!el) return;
  if (text == null) {
    el.classList.add('hidden');
    return;
  }
  el.innerHTML = (spinning ? _nixosLogoSvg(true) : '') + '<span>' + _escHtml(text) + '</span>';
  el.classList.remove('hidden');
}

function connectTerminalWs() {
  if (_termWs) { _termWs.close(); _termWs = null; }
  _termReady = false;
  _termReadyWaiters = [];
  _termExited = false;
  _termWs = new WebSocket(_TERM_WS_BASE);
  _termWs.binaryType = 'arraybuffer';
  _termWs.onopen = () => {
    _termReconnectAttempts = 0;
    if (_termReconnectTimer) { clearTimeout(_termReconnectTimer); _termReconnectTimer = null; }
    _setTermStatusBanner(null);
    // Deferred by the same ~200ms the ResizeObserver above debounces by (see its own comment)
    // -- opening the panel and connecting happen in the same breath on a cold start (toggleTerminal()
    // synchronously starts both), so fit() here can otherwise run mid-transition (the panel's
    // CSS height animating from collapsed to open, ~180ms) and measure a near-zero-height
    // container. That produced a degenerate resize (seen in testing: 1 row) sent to a session
    // that then ran real commands into an unusably tiny pane -- looking like the command never
    // ran, when it was actually just rendered somewhere no one could see it.
    setTimeout(() => {
      if (_term && _termFit && _termWs && _termWs.readyState === WebSocket.OPEN) {
        // fit() forces an actual fresh layout/cell-metrics measurement and applies it to _term;
        // proposeDimensions() alone is a pure calculation that can be stale right after a fast
        // reconnect (e.g. right after a "Reconnecting..." banner was showing) -- reading _term.cols/rows after
        // fit() is the same authoritative value a genuine resize event would produce. Sent
        // unconditionally (not just when fit() itself changes _term's size and fires onResize)
        // since THIS browser's actual current size should always apply regardless of whatever a
        // persistent session was last told -- a brand new shell has no size at all yet, and a
        // reused one may have last been resized by a different tab/window entirely.
        _termFit.fit();
        const cols = _term.cols, rows = _term.rows;
        // A single message straight to this browser's actual current size. Whether that needs to
        // turn into a real, sustained two-step resize (to force a foreground full-screen app like
        // htop to redraw on reattach) is decided server-side now, not here -- see the resize
        // handling in _terminal_ws() (eznix-terminal.py) for why that decision needs to see the PTY's
        // own byte stream (whether a full-screen app has switched into the alternate screen
        // buffer), which only the server can.
        _termWs.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    }, 200);
  };
  _termWs.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) { if (_term) _term.write(new Uint8Array(e.data)); return; }
    // A text frame is always a control message from the server -- real terminal output is
    // always sent binary (see above) -- never raw content to print.
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'ready') {
        _termReady = true;
        const waiters = _termReadyWaiters;
        _termReadyWaiters = [];
        waiters.forEach(fn => fn());
      } else if (msg.type === 'exited') {
        _termExited = true;
      }
    } catch {}
  };
  _termWs.onerror = () => {
    // onclose always follows a WebSocket error, and handles the user-facing status banner --
    // nothing extra needed here.
  };
  _termWs.onclose = (e) => {
    if (_termExited) {
      // The shell process itself actually exited (any way -- "exit", Ctrl+D, etc.), not just a
      // dropped connection -- signaled explicitly by the server (see _termExited's own comment
      // above), since under session persistence a plain closed/dropped connection no longer
      // implies that on its own. Destroying the whole terminal instance rather than trying to
      // reset/reuse it means the next open (initTerminal(), whose `if (_term) return` guard now
      // sees null) builds a genuinely fresh one from scratch -- no stale buffer content possible,
      // since nothing survives to leave one.
      if (_term) { _term.dispose(); _term = null; }
      _termFit = null;
      _termOnData = null;
      const panel = document.getElementById('terminal-panel');
      if (!panel.classList.contains('collapsed')) toggleTerminal();
    } else {
      // Just a dropped/closed connection -- the shell itself is still running server-side (see
      // bin/eznix-terminal.py's _SESSION), so reconnecting reattaches to it and replays what was missed
      // rather than starting over. Keep the existing _term (and whatever's already on screen) and
      // just retry.
      if (_termReconnectAttempts < 10) {
        _setTermStatusBanner('Reconnecting', true);
        _termReconnectAttempts++;
        const delay = Math.min(500 * _termReconnectAttempts, 5000);
        _termReconnectTimer = setTimeout(() => connectTerminalWs(), delay);
      } else {
        _setTermStatusBanner('Could not reconnect to terminal service.');
      }
    }
  };
  if (_termOnData) { _termOnData.dispose(); _termOnData = null; }
  // No reset-on-connect needed here: a genuinely fresh _term (new Terminal(), first load or
  // just recreated after a clean exit -- see onclose above) already starts empty, and a
  // reconnect that reuses an existing _term (e.g. after a dropped connection) should keep
  // showing its old content, with the new shell's output just appended below -- not confusing
  // enough to be worth clearing for.
  _termOnData = _term.onData((data) => {
    if (_termWs && _termWs.readyState === WebSocket.OPEN) _termWs.send(data);
  });
}

// Persisted across reloads, independent of the terminal session itself (which is shared, server-
// side, not tied to any one browser at all -- see bin/eznix-terminal.py's _SESSION) -- this is purely
// "was the panel showing, and how big" per-browser UI state, same convention as
// eznix-tree-visible. Restored once at init, below.
function _persistTerminalOpen(open) {
  try { localStorage.setItem('eznix-terminal-open', open ? 'true' : 'false'); } catch (e) {}
}
function _persistTerminalSize(size) {
  try { localStorage.setItem('eznix-terminal-size', size); } catch (e) {}
}

function toggleTerminal() {
  const panel = document.getElementById('terminal-panel');
  const btn = document.getElementById('term-toggle');
  const collapsed = panel.classList.contains('collapsed');
  if (collapsed) {
    panel.classList.remove('collapsed');
    panel.style.height = panel._openHeight || '25vh';
    btn.classList.add('expanded');
    btn.dataset.tooltip = 'Hide';
    _persistTerminalOpen(true);
    initTerminal().then(() => {
      if (_term) {
        if (!_termWs || _termWs.readyState === WebSocket.CLOSED) connectTerminalWs();
        _term.focus();
      }
    });
  } else {
    panel._openHeight = panel.style.height || '25vh';
    // No need to also set panel.style.height here: the .terminal-panel.collapsed(.install-mode)
    // CSS rules (!important) already decide the visible height on their own, regardless of
    // whatever the inline style still says.
    panel.classList.add('collapsed');
    btn.classList.remove('expanded');
    btn.dataset.tooltip = 'Show';
    _persistTerminalOpen(false);
  }
}

// Hides the open terminal panel on a press anywhere outside it, when TERMINAL_AUTO_HIDE. On
// mousedown rather than click: a text selection dragged out of the terminal and released over
// the editor ends in a click on their common ancestor, which would count as "outside". A menu
// counts as inside -- a command button's own dropdown is appended to <body>, not the panel, and
// picking a command from it must not hide the terminal it's about to run in -- and so does the
// restart popup, which sits just above the panel.
function initTerminalAutoHide() {
  if (!TERMINAL_AUTO_HIDE) return;
  const panel = document.getElementById('terminal-panel');
  document.addEventListener('mousedown', e => {
    if (panel.classList.contains('collapsed') || panel.contains(e.target)) return;
    if (_ctxMenuStack.some(m => m.contains(e.target))) return;
    if (e.target.closest && e.target.closest('#term-restart-popup, .hover-tooltip')) return;
    toggleTerminal();
  }, true);
}

function setTerminalSize(size) {
  const panel = document.getElementById('terminal-panel');
  let h;
  if (size === 'full') {
    const taken = ['.header', '.tab-bar-row', '.force-type-bar', '.statusbar']
      .reduce((sum, sel) => {
        const el = document.querySelector(sel);
        return sum + (el && !el.classList.contains('hidden') ? el.offsetHeight : 0);
      }, 0);
    h = `calc(100vh - ${taken}px)`;
  } else {
    h = size === 'half' ? '50vh' : '25vh';
  }
  panel._openHeight = h;
  panel.style.height = h;
  panel.classList.remove('collapsed');
  document.getElementById('term-toggle').classList.add('expanded');
  _persistTerminalOpen(true);
  _persistTerminalSize(size);
  initTerminal().then(() => {
    if (_term) {
      if (!_termWs || _termWs.readyState === WebSocket.CLOSED) connectTerminalWs();
      _term.focus();
    }
  });
}

// STATIC_BUTTONS (from eznix.toml's [[buttons]] — see eznix.py/nix/nixos.nix) is deploy-
// time, not tied to any config file. services.eznix.buttons can also be set in any *.json tab —
// every such button shows regardless of which tab is active. Every tab's config is kept in
// fileConfigs (loaded at startup), so this doesn't need a fetch.
//
// These two sources aren't as independent as they look: services.eznix.buttons is one NixOS
// option either way — setting it in a *.json file inside CONFIG_DIR isn't some eznix-only
// concept, that file gets merged by json2nix.nix into the very same option nix/nixos.nix
// reads to generate eznix.toml's [[buttons]] in the first place. So the moment you save that
// file and nixos-rebuild, its buttons start arriving as STATIC_BUTTONS too — the *same* button
// definitions reaching getAllButtons() from both directions.
//
// An earlier version tried to dedupe these by matching content (label+command, or every field, or
// a generated id) so the stale deployed copy could be dropped in favor of the live one — every
// variant of that either broke on a rename (whatever the match relied on is exactly what a rename
// changes) or required writing extra state into the *.json files. `static` sidesteps the
// whole problem instead of solving the matching: STATIC_BUTTONS is only shown when explicitly
// marked static = true (meant for a button declared directly in Nix, never through the eznix
// UI, that should just always be there) — otherwise a *.json-declared button is the *only* place
// that button is read from, full stop, so there's nothing to reconcile it against and nothing a
// rename could possibly desync. The trade-off: a button meant to always show has to be flagged
// that way explicitly; it can't rely on STATIC_BUTTONS being un-superseded by default the way it
// used to.
// Any button field can individually be right-click-disabled like any other option (it's a
// regular object under an array item, not the array item itself, which is the only thing the
// disable action is barred on) -- that wraps it as { _disabled: true, _value: <original> },
// which every reader below (_renderButtonRow, runButton) would otherwise treat as a truthy,
// non-empty value (rendering literally as "[object Object]" for something like `menu`, or trying
// to run it as a shell command for `command`). Unwrapping to `undefined` here — not to the
// preserved _value — matches what actually happens once deployed: json2nix.nix excludes a
// disabled field from the Nix merge entirely, so the option reverts to its real default, same as
// never having been set. Only done for per-file buttons; STATIC_BUTTONS comes from deploy-time
// TOML, which has no way to express this wrapper in the first place.
function _unwrapButtonField(v) {
  return isDisabled(v) ? undefined : v;
}
function _normalizeButton(b) {
  return {
    label: _unwrapButtonField(b.label),
    command: _unwrapButtonField(b.command),
    save_first: _unwrapButtonField(b.save_first),
    clear_first: _unwrapButtonField(b.clear_first),
    menu: _unwrapButtonField(b.menu),
    mode: _unwrapButtonField(b.mode),
  };
}
function getAllButtons() {
  const perFile = files.flatMap(f => fileConfigs[f]?.services?.eznix?.buttons || [])
    .map(_normalizeButton);
  const staticSurviving = STATIC_BUTTONS.filter(b => b.static === true);
  return [...staticSurviving, ...perFile];
}

function renderButtons() {
  // Rebuilds the whole button bar below, which can shift/invalidate the indices any currently
  // open button dropdown was built from (getAllButtons() re-runs fresh each render) — close it
  // rather than leave it showing stale entries that could now run the wrong command.
  _closeContextMenu();
  const container = document.getElementById('terminal-cmd-btns');
  const installContainer = document.getElementById('terminal-cmd-btns-install');
  if (!container || !installContainer) return;
  container.innerHTML = '';
  installContainer.innerHTML = '';
  const buttons = getAllButtons();
  const dirty = isAnyDirty();
  // Each entry keeps its index into the *full* buttons list — runButton()/showButtonMenu() both
  // index into that same full list, so splitting into two rows here doesn't need to change
  // either of them.
  const entries = buttons.map((btn, idx) => ({ btn, idx }));
  _renderButtonRow(installContainer, entries.filter(e => e.btn.mode === 'install'), buttons, dirty);
  _renderButtonRow(container, entries.filter(e => e.btn.mode !== 'install'), buttons, dirty, INSTALL_MODE ? 'Disabled in install mode' : null);
}

// disabledTitle, when set, overrides every button's own title in this row (used for the ordinary
// row during install mode) — set directly on each button rather than relying on the container's
// own title showing through its pointer-events: none children on hover, which isn't consistent
// enough across browsers to depend on.
function _renderButtonRow(container, entries, buttons, dirty, disabledTitle) {
  const seenMenus = new Set();
  entries.forEach(({ btn, idx }) => {
    if (btn.menu) {
      // menu is a "/"-separated path (e.g. "Disk/Advanced") — only the first segment groups at
      // bar level; the rest nests as a submenu inside that dropdown (see _buildButtonMenuItems).
      // Every button sharing this top segment renders as one dropdown, at the position of
      // whichever of them appears first — later members are skipped here since they're already
      // covered by that one group button.
      const topMenu = btn.menu.split('/')[0];
      if (seenMenus.has(topMenu)) return;
      seenMenus.add(topMenu);
      const idxs = entries.filter(e => e.btn.menu && e.btn.menu.split('/')[0] === topMenu).map(e => e.idx);
      const b = document.createElement('button');
      b.className = 'btn term-run-btn';
      b.textContent = topMenu;
      // No content-listing tooltip here (unlike a plain button's command, below) -- opening the
      // dropdown already shows exactly what's inside, so a hover tooltip would just be a
      // redundant extra step before seeing the same thing. Still explains *why* it's disabled
      // in install mode, though, since the dropdown can't be opened at all to see that.
      if (disabledTitle) _wireHoverTooltip(b, disabledTitle);
      b.onclick = e => showButtonMenu(e, idxs);
      container.appendChild(b);
      return;
    }
    const b = document.createElement('button');
    b.className = 'btn term-run-btn';
    b.textContent = btn.label || '(no label)';
    _wireHoverTooltip(b, disabledTitle || btn.command);
    if (btn.save_first) {
      b.dataset.saveFirst = '1';
      b.disabled = dirty;
    }
    b.onclick = () => runButton(idx);
    container.appendChild(b);
  });
}

// Turns a flat list of {btn, idx, path} entries into a showContextMenu()-compatible items array,
// recursively — an entry with no path segments left becomes a leaf (runs the button); entries
// still sharing a next segment collapse into one {label, items} submenu-trigger, which
// _buildMenuLevel() renders as a click-to-open nested flyout instead of a plain action.
function _buildButtonMenuItems(entries, dirty) {
  const items = [];
  const seenGroups = new Set();
  entries.forEach(({ btn, idx, path }) => {
    if (path.length === 0) {
      items.push({
        label: btn.label || '(no label)',
        title: btn.command,
        disabled: !!btn.save_first && dirty,
        onclick: () => runButton(idx),
      });
      return;
    }
    const head = path[0];
    if (seenGroups.has(head)) return;
    seenGroups.add(head);
    const sub = entries
      .filter(e => e.path[0] === head)
      .map(e => ({ btn: e.btn, idx: e.idx, path: e.path.slice(1) }));
    items.push({
      label: head,
      title: sub.map(e => e.btn.label || '(no label)').join(', '),
      items: _buildButtonMenuItems(sub, dirty),
    });
  });
  return items;
}

// The dropdown a grouped button (btn.menu) opens — same left-click-reuses-showContextMenu trick
// as showExportMenu()/showBackupsMenu(), anchored to the group button's own bottom-left corner.
// save_first is honored per item rather than for the group button itself (a menu can mix
// save_first and non-save_first commands), and re-checked at open time via isAnyDirty() rather
// than baked in at the last renderButtons() — the button bar isn't otherwise re-rendered on every
// keystroke, only _updateDirty()'s direct dataset-based toggle is, which only reaches standalone
// buttons.
function showButtonMenu(event, idxs) {
  const btn = event.currentTarget;
  const btnRect = btn.getBoundingClientRect();
  // Anchored to the enclosing bar's own top, not the button's -- .terminal-header is taller
  // than the 26px button in it (--term-bar in terminal.css), so the bar
  // has some space of its own above the button that the menu should sit flush against
  // instead of stopping short at the button's own (lower) top edge. Horizontal position still
  // comes from the button itself (left/right), just the vertical reference point changes.
  const barRect = btn.closest('.terminal-header')?.getBoundingClientRect();
  const rect = barRect
    ? { left: btnRect.left, right: btnRect.right, top: barRect.top, bottom: barRect.bottom }
    : btnRect;
  const anchor = {
    preventDefault: () => event.preventDefault(), stopPropagation: () => event.stopPropagation(),
  };
  const buttons = getAllButtons();
  const dirty = isAnyDirty();
  // The bar-level dropdown already consumed the shared first "/" segment — strip it here so each
  // entry's remaining path is what's left to group into (nested) submenus.
  const entries = idxs.map(idx => ({
    btn: buttons[idx], idx,
    path: buttons[idx].menu.split('/').slice(1),
  }));
  // Opens above the button (the bar sits at the bottom of the page) — see _positionMenuAboveAnchor.
  // Windows' Start-menu pattern: the top-level menu is a dropup, but any nested submenu inside it
  // (see _positionSubmenu) still cascades to the side, aligned with whatever row triggered it.
  // triggerEl: btn is what makes a second click on the same button toggle it closed.
  showContextMenu(anchor, _buildButtonMenuItems(entries, dirty), { anchorRect: rect, triggerEl: btn });
}

function runButton(idx) {
  const btn = getAllButtons()[idx];
  if (!btn) return;
  _runInTerminal(btn);
}
// Type a command into the terminal and run it, opening the panel first if it's closed.
function _runInTerminal(btn) {
  const panel = document.getElementById('terminal-panel');
  if (panel.classList.contains('collapsed')) toggleTerminal();
  initTerminal().then(() => {
    if (!_term) return;
    if (!_termWs || _termWs.readyState === WebSocket.CLOSED) connectTerminalWs();
    // Waits for the server's explicit "ready" signal (see connectTerminalWs()'s onmessage)
    // rather than the WebSocket's own open state or the first byte of output -- either of those
    // can arrive before the shell on the other end is actually ready to receive input, which
    // silently swallows it instead of running the command.
    _waitTermReady().then(() => {
      if (_termWs) _termWs.send('\x15'); // clear whatever's half-typed at the prompt, always
      // Defaults to true (matching buttons.*.clear_first's own Nix-side default) for a button
      // declared in a *.json file with no clear_first key at all -- a deploy-time (TOML) button
      // always carries an explicit true/false by the time it gets here (see nix/nixos.nix),
      // so this fallback only ever engages for the live, pre-rebuild JSON case.
      if (btn.clear_first !== false) {
        if (_term) _term.clear();
        if (_termWs) _termWs.send('clear\r');
      }
      if (_termWs) _termWs.send(btn.command + '\r');
    });
  });
}

// ── What the page tells the terminal ───────────────────────────────────────────
eznix.on('init', () => {
  initTerminalAutoHide();
  if (INSTALL_MODE) {
    document.getElementById('terminal-panel').classList.add('install-mode');
    document.getElementById('terminal-header-install').classList.remove('hidden');
    const ordinaryRow = document.getElementById('terminal-cmd-btns');
    ordinaryRow.classList.add('install-mode-disabled');
    _wireHoverTooltip(ordinaryRow, 'Disabled in install mode');
  }
});
// Restores via setTerminalSize() rather than toggleTerminal() -- it recomputes the actual
// height from the size name fresh against the current window (needed for "full" regardless,
// since that's a live calc() against other elements' heights), rather than relying on
// panel._openHeight, a plain JS property that never survives a reload.
eznix.on('ready', () => {
  if (localStorage.getItem('eznix-terminal-open') === 'true') {
    setTerminalSize(localStorage.getItem('eznix-terminal-size') || 'quarter');
  }
});
eznix.on('render', renderButtons);
eznix.on('dirty', dirty => {
  document.querySelectorAll('.term-run-btn[data-save-first]').forEach(b => { b.disabled = dirty; });
});
eznix.on('theme', () => {
  if (_term) _term.options.theme = _buildTermTheme();
  // A theme swap can also change --term-padding, which affects #term-output's content box
  // without changing its own outer size — the ResizeObserver that normally drives fit() only
  // fires on an actual element resize, so without this explicit call the terminal keeps
  // rendering at its old size until something else forces a fresh fit().
  if (_termFit) _termFit.fit();
});
// The terminal is a separate process that isn't restarted along with the server, so its
// hashes are tracked on every ping, whatever else that ping says.
eznix.on('ping', data => {
  _terminalStale = data.terminal_stale === true;
  _updateTermRestartPopup();
});
