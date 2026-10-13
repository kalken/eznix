# Themes

How eznix's themes are put together, and what to keep to when making a new one — a built-in
theme, or one of your own.

## What a theme is

One CSS file with a single `:root` block of variables. Nothing else: no selectors, no layout.
`webroot/style.css` holds every rule and only ever refers to those variables, so a theme can
change colours, fonts, corner radii and spacing, and nothing structural.

The built-in themes are `webroot/theme-<name>.css`: `nixos`, `gruvbox`, `osx-dark`,
`osx-light`, `breeze-dark`, `breeze-light`, `gnome-dark`, `gnome-light`. (`osx`, `breeze` and
`gnome` are not files: each stands for
whichever of its two themes matches the light or dark appearance of the system the browser
runs on.) Any of them is a complete list of the variables there are, grouped under the same
headings in the same order.

## Choosing colours

A theme needs very few colours. Everything on screen comes from three small groups, and the
long list of variables is mostly the same handful of values used again.

**1. One ramp of neutrals.** Pick a single grey — or a single hue at low saturation, as `nixos`
(blue) and `gruvbox` (warm brown) do — and take steps along it:

- four background steps: page, bars, hover, raised (`--bg` to `--bg4`), plus the card
- one text colour at the far end of the ramp, with two dimmer versions mixed back toward the
  background
- borders, popups, selection, the active tab, scrollbars: more steps on the *same* ramp, each
  placed between two of the above

Nothing in this group should introduce a new hue. If a border or a hover shade looks like a
different colour from the surface it sits on, it's off the ramp.

**2. At most one accent.** One hue for links, focus rings and, if wanted, the filled controls.
It is optional: both `osx-*` themes have none and use greys from the ramp instead.
Two accents compete; there is no second one to set.

**3. Four signal colours, one job each.** These are the only saturated colours a neutral theme
has, which is what makes them noticeable.

| Colour | Variable | Means |
|---|---|---|
| Green | `--green`, `--green2` | fine: saved, valid — and the colour of a *value* wherever one is quoted: a Nix expression, a default or example in an option's documentation popup |
| Red | `--red` | wrong or destructive: a missing required option, an error, delete |
| Yellow / orange | `--dirty-color` | unsaved changes |
| Purple | `--purple` | reference text: types, wildcards and existing paths in autocomplete, inline code in documents |

Keep them to those jobs. A theme that also uses green or red decoratively takes away the one
thing they are for.

So a new theme is roughly ten decisions: the ramp's hue, its darkest and lightest ends and the
steps between, the text colour, an accent or none, and four signals. As a check, both `osx-*`
themes use about twenty distinct greys and five other colours for the whole interface.

The terminal is the exception — it has sixteen colours of its own, because programs running in
it expect them (see "Terminal" below).

The two `osx-*` themes are the reference for how roles are assigned. Where the others once
differed (a status bar darker than the other bars, popups the same colour as the bars, an
accent-coloured toggle knob, grey standing in for purple) they have been brought in line; a new
theme should match them too. The one deliberate difference left is section names, which `nixos`
and `gruvbox` show in their accent and the neutral themes in a text colour.

## The surfaces

Four backgrounds stack on top of each other. Get these right first; most of a theme's look
comes from them.

| Surface | Variable | Notes |
|---|---|---|
| The editor page | `--editor-bg` (normally `var(--bg)`) | Also the terminal's background, via `--term-bg` |
| Bars and panels: top bar, tab bar, status bar, terminal bar | `--bg2` | The status bar has its own variable, `--statusbar-bg`; keep it `var(--bg2)` so every bar is one colour |
| A top-level section's card | `--card-bg` (normally `var(--bg2)`) | The bars' colour in every built-in theme; must be told apart from the page it sits on |
| A tab that is not the open one | `--tab-bg`, `--tab-border` (normally `var(--bg3)` and `var(--border2)`) | A button's fill and line; the `osx-*` and `breeze-*` themes have none, a tab there being a name until it is the open one |
| An option's value cell, inside a card | `--value-bg` | Defined as halfway between card and page; leave it derived |

- **Page and card need visible contrast, and cards are the colour of the bars.** A dark theme
  has the page darkest and the bars and cards a step lighter; a light theme has a grey page
  with white bars and cards (`breeze-light` the other way round, white page and grey bars and
  cards, since that is where Dolphin has those two colours).
- **Or a line in place of the fill.** `--card-border` is the line around a card (normally
  `var(--panel-hairline)`), and `--value-border` one around a value strip (normally
  `transparent`, which is none). No built-in theme uses them that way; they are there for a
  theme of your own that wants outlines.
- **`--bg3` and `--bg4` are hover and raised shades**, used on buttons, list rows and inline
  code. Each has to move one step further away from `--bg2`, in the same direction (lighter in
  a dark theme, darker in a light one), or hover states disappear.
- **Popups** (`--popup-bg`, `--select-option-bg`) sit above everything and want their own
  shade, not the page's. `--popup-bg` is one surface shared by dialogs, the documentation popup
  over an option and the search results, so those always match each other. `--search-file-color`
  is the file a search result is in, a line of small text on that surface: pick something
  readable there that is neither the path's colour (`--text2`) nor the value's.
- **Edges are shadows, not borders**: `--panel-hairline` is the 1px line along a bar or card,
  `--panel-shadow` the soft shadow beside it. Both are translucent black, so they need lowering
  a lot on a light theme and barely show on a very dark one.

## Text

- `--text` for values and option names, `--text2` for secondary text, `--text3` for the
  dimmest (placeholders, hints). Define the two dimmer ones as a mix of `--text` toward the
  background rather than as separate greys, so they stay in step.
- **Section names** take `--section-key-color`. Full-strength `--text` reads as too heavy for
  them on a light theme; `--text2` is what `osx-light` uses.
- **Anything used as a text colour must be readable on a card**: `--accent`, `--green`,
  `--red`, `--purple`, `--dirty-color`. On a light theme that means the darker variants of a
  colour, not the bright ones that work on black.

## Accent

`--accent` is used as text (links, inline code); `--accent2` for outlines: focus rings, drop
targets, the flash on a newly added option. The filled controls have their own variables —
`--toggle-on-bg`, `--btn-primary-bg`, `--selected-bg`, `--select-option-hover` — so they can
follow the accent or not.

- A theme can be entirely neutral: both `osx-*` themes use greys for all of these.
- A toggle's knob (`--toggle-on-knob`) is white, or the palette's lightest neutral — not the
  accent — whatever the toggle itself is filled with.
- If the primary button is filled with the accent, check its label (`--btn-primary-text`)
  against that fill.
- `--select-option-hover` is behind menu and dropdown items whose text keeps its normal
  colour. Don't make it so saturated that `--text` on it stops being readable.
- A destructive menu item fills with `--red` on hover and shows `--danger-text` on it, so
  those two have to work together.

## The logo

The NixOS logo (it turns while the terminal reconnects) is drawn in two colours, every other
arm: `--logo-1` and `--logo-2`. `nixos` uses the logo's own two blues, the
others their two accents. A theme that sets neither gets `--accent2` and `--accent`.

The tab's icon is the same logo in the same two colours, with nothing behind it. So
is the icon of the page installed as an app, except on a Mac, where it sits on the colour of
the header (`--bg2`): an app's icon can't be transparent there. That one is in the colours of the theme set as `theme`, not of one
picked with the swatches: the browser fetches it by itself, and shows a new one only after
the app has been closed and opened again.

## Spacing

The "Editor layout" block is the same in every built-in theme, on purpose:

| Variable | Value | |
|---|---|---|
| `--page-margin` | 20px | around the cards, on every side |
| `--section-gap` | 16px | between two top-level cards |
| `--block-pad` | 10px | inside a card, at the sides |
| `--row-height` | 24px | a row: one line of text with 4px above and below it |
| `--card-gap` | 4px | above and below a box inside a card (a sub-section, or a run of plain options), each of which has a line along its top |
| `--indent-step` | 2ch | per level of nesting |
| `--nested-section-gap` | 0px | below a foldable section, in addition to its rows |

Inside a card everything is rows, one after the other; the only other space is a box's padding
at a divider line. With the values above, any line of text is 8px from what is above it, text
or line. The margins and the gap between cards follow the figures Apple has published for
window margins and for spacing between groups. A theme that is only about colour should leave the whole block alone; change it
in all of them or none.

Corner radii are the same in every built-in theme too — `--radius` 8px (cards, panels, popups),
`--radius-sm` 5px (tabs, buttons), `--input-radius` 6px — taken from the `osx-*` themes. They
stay variables in each theme file so a user theme can still choose its own.

`--font` is the theme's to choose. Keep it monospaced: values are configuration and Nix code.

## Terminal

`--term-*` are xterm.js's colours, read out of the page once the theme has loaded.

- `--term-bg` normally stays `var(--editor-bg)`.
- All sixteen ANSI colours have to be readable on it, "white" and "bright black" included.
  On a light background that takes a deliberately darker set; a palette designed for a black
  terminal will not do.

## The swatch

Each theme has a dot in the header. Paint it with the theme's own page background (`--bg`) and
give it a ring in the accent, or a neutral grey if the theme has no accent. Swatches are sorted
from darkest to lightest by that colour every time the page loads, so there is no order to
maintain — but a swatch painted with some other colour will sort into the wrong place.

## A theme from a screenshot

A theme that is to look like a desktop is made from a screenshot of that desktop's file
manager (Finder, Dolphin, Files) in the appearance wanted. The colours are measured in the
picture's pixels, never judged by eye and never taken from a list of named colours alone: a
system's own names say what a surface is called, not what ends up on screen (macOS names
`#1e1e1e` for a window that Finder draws as `#232323`). Each part of the window gives one
thing here:

| In the file manager | Becomes | Variable |
|---|---|---|
| The window's own surface, which the toolbar has too | the bars and the cards | `--bg2`, `--card-bg` |
| A panel of another shade in the window: the sidebar | the editor's page | `--bg`, `--editor-bg` |
| The line round that panel, and the lines between columns | the line round a card and every thin line | `--panel-hairline`, `--card-border` |
| A button of the toolbar: its fill and its rim | a button | `--bg3`, `--border2` |
| An entry of the sidebar that is not selected | a tab | `--tab-bg`, `--tab-border` |
| The selected entry: its fill and the colour of its name | the open tab | `--tab-active-bg`, `--tab-active-border`, `--tab-active-text` |
| A file's name | text | `--text` |
| The dimmer column beside it (kind, date) | dimmer text | `--text2` |
| What the selection or a link is coloured with | the accent, if the theme has one | `--accent` |

That reading is the user's, given with a Finder window (2026-10-13). A fill measured on one
ground and used on another keeps its distance from the ground, not its value (the selected
entry is #282828 on Finder's #1a1a1a sidebar and #313131 on the #232323 bar here). A rim
two pixels wide in a picture taken at double size is one line here, of the colour between
the two.

Everything else follows from those by the rules above: the value strip stays derived, the
remaining greys are steps between the measured ones, and the signal colours are the
system's own. Only colours come from the picture: the layout, the spacing and the shapes
are the same in every theme. The `osx-*` and `breeze-*` themes were made this way, from Finder and from Dolphin; a
scheme's own file, where there is one, is the check that the picture's colours are true
(Breeze's Window, View and Header colours were in the screenshot to the digit).

## Adding a built-in theme

1. `webroot/theme-<name>.css`: copy the closest existing one. It must define exactly the same
   set of variables as the others.
2. `bin/eznix.py`: add the name to `BUILTIN_THEMES`.
3. `webroot/index.html`: add it to `_THEMES`, and add its swatch button to `.theme-switcher`.
4. `webroot/style.css`: add its `.theme-swatch-<name>` colours.
   (A light and dark pair gets one dot between them instead, for the name that follows the
   system: add that name to `_AUTO_THEMES` there and to `AUTO_THEMES` in `eznix.py`, as `osx`,
   `breeze` and `gnome` are.)
5. `nix/options.nix`: add it to the `theme` option's description.
6. `README.md` and `example/eznix.example.toml`: add it where the themes are listed.

Names are lowercase letters, digits, `-` and `_`.

**A new variable goes into every built-in theme file at once.** `style.css` has no fallbacks,
so a variable missing from one theme is simply a missing colour there.

## Your own theme

A user theme is the same kind of file, with one difference: it doesn't have to be complete. A
built-in theme is loaded underneath it, so it only sets what it wants to change, and it keeps
working when a later version adds a variable.

```css
/* base: osx-dark */
:root {
  --bg:     #1b1622;
  --bg2:    #261f30;
  --accent: #c792ea;
}
```

- The `base` comment, near the top of the file, names the built-in theme underneath. It is
  `nixos` when left out. Pick a base of the same kind, light or dark, as the theme you're
  making: everything the file doesn't set comes from there.
- If it is of the other kind than its base, say so: `--color-scheme: only light;` in a light
  theme on a dark base, `--color-scheme: dark;` the other way round. That is what tells the
  browser which the page is, so that it draws its own parts (a menu's list) to match and
  does not darken a page by force that it takes for a light one.
- Set `--bg` and `--accent` as plain hex colours. They are what the swatch is painted with;
  without them it is a grey dot that sorts into the middle of the row.
- Hooking it up is in the README, under "Your own themes": `services.eznix.themes` in the
  module, or a `themes_dir` folder of `<name>.css` files standalone. The folder is read when
  the server starts.
- A name already taken by a built-in theme is skipped.

## Before calling it done

Look at it in the browser, at least at:

- a file with several sections, nested ones folded and unfolded, and a list of objects
- a toggle on and off, a dropdown open, a right-click menu, a hover tooltip
- a required-but-missing option and the unsaved-changes indicator
- the terminal, with something colourful running (`ls --color`, `git diff`)
- the login page, including a field the browser has autofilled
