# Myink Design System

## Design Read

Myink is a focused long-form fiction workbench for authors. The interface should feel precise, quiet, and dependable: a warm paper surface that carries reading and writing, with compact tool chrome around it. It is a product UI, not a marketing dashboard.

The default theme is paper, not a dark shell. Night and high-contrast are full alternates that redefine the same token names — not overlays on top of paper.

## Direction

- Product language: focused, editorial, technical, calm.
- Visual density: medium. Keep the writing surface dominant and tool chrome compact.
- Motion: restrained. Animate state changes and progress, never decorate empty space.
- Shape language: 8px for controls, 12px for panels, 16px for large framed surfaces. `999px` and `50%` are
  shape semantics (pill, circle), not size tiers. Outside those, the only value in the build is `0` — a
  deliberate square, not a fourth tier.
- Use one accent color consistently. Do not use gradients, glassmorphism, or decorative glow. Two bounded exceptions exist: the feedback lamp's downward beam (on by default, and the reader can turn it off in theme settings), and media backgrounds a user chooses for their own theme.
- Prefer separators, spacing, and surface contrast over floating card stacks. Hierarchy comes from four lightness steps plus 1px rules; shadows are reserved for things that genuinely float.
- The accent means "this is the item you are reading". A mode switch (长篇 / 短篇) is a neutral segmented control — inset border and weight carry its selected state, never the accent, because a mode is not a location.
- Breakpoints are a documented literal ladder: `420 / 640 / 900 / 1200`. Every stylesheet either handles those tiers or carries an explicit exemption comment backed by a measured number — "it looks fine" is not an exemption.

## Color Tokens

`web/src/styles/tokens.css` is the only place shell colors are authored — at 100% opacity, what that file says
is what renders. `lib/theme.ts` derives `THEME_SHELLS`, `CUSTOM_INLINE_VARS`, and the layer lists by parsing
that same file (`tokens.css?raw`) instead of re-typing the variable names, because the opacity slider runs
`fade()` on literal hex values and a hand-copied fourth list drifts silently. `lib/theme.test.ts` asserts that
the 13 tokens the slider dilutes are each defined, non-empty, and present in `tokens.css` under all three
official themes — forget one and the suite goes red instead of that layer silently ignoring the slider.

```css
:root {
  /* Surfaces: four opaque lightness steps, dark to light. */
  --canvas: #efeadd;        /* page ground */
  --surface-1: #fbf8f1;     /* panels, rail, inputs */
  --surface-2: #f6f2e8;     /* recessed / secondary */
  --surface-3: #f6f2e8;     /* paper collapses 2 and 3; night and contrast keep them apart */
  --line: #e8e1d5;
  --line-strong: #d8cfc0;
  --editor: #fffdf9;        /* the paper the prose lives on — the brightest step */
  --editor-ink: #514a43;    /* prose is a shade softer than UI ink: the eye is on it for hours */
  --editor-muted: #817970;

  /* Ink: four steps, ~5–6 L* apart so main / secondary / tertiary / hint stay separable.
     `--ink-faint` sits right at 4.5:1 on --surface-1; it cannot get lighter. */
  --ink: #3f3a36;
  --ink-muted: #5d5650;
  --ink-subtle: #6d645d;
  --ink-faint: #7a7068;

  /* One accent. It is a *surface* color: #9fd8ad as text on paper measures 1.47:1.
     Anything written in the accent uses --accent-ink (4.90:1 on the darkest surface),
     and hover goes darker, not lighter — --link-hover was once #5e946c (3.19:1),
     which made hovering a link harder to read than leaving it alone. */
  --accent: #9fd8ad;
  --accent-hover: #89c99b;
  --accent-pressed: #7ab88d;
  --accent-ink: #476d50;
  --link-hover: #3f6249;
  --focus: #6eab7f;
  --accent-soft: #e2f3df;

  --success: #2f7346;
  --warning: #8a5a10;
  --error: #a8443c;
}
```

Panels are opaque. They used to be `rgba(255,255,252,.86)` over the canvas, which minted a fifth cream
within one ΔE of the fourth and washed the hierarchy out. Layering is lightness plus 1px rules now; to let
a wallpaper through, the reader lowers 界面透明度 instead.

`accent-color` is set globally to `--link-hover`; without it the range sliders render in UA blue, the one
color on screen that belongs to no theme.

Night (`html[data-theme='night']`) and high-contrast (`html[data-theme='contrast']`) redefine this whole
set. Night: `--canvas #121212`, `--surface-1/2/3 #1c1c1c / #242424 / #2c2c2c`, `--editor #181818`,
`--accent #7dba90` (8.3:1 as text, so its `--accent-ink` equals it). Contrast: pure white canvas and
editor, `--ink #141414`, `--accent #1f7a3a` — a saturated green that works as both surface and text.
`html[data-theme='custom']` inherits paper and re-points only the accent family at the user's own color.
Severity has its own color ramp (`--sev-*`), and it is one of three channels — text label, color, and a 1px
border — never the only one.

## Typography

Six levels, all of them hanging off one user knob. The reader picks 阅读字号 in `/theme`; every other size
is a fixed multiple of it, so the proportions never shift when the text gets bigger.

| Token | Definition | What it is for |
| --- | --- | --- |
| `--text-display` | `body × 2.44` | page title |
| `--text-title` | `body × 1.43` | section / chapter heading |
| `--text-heading` | per tier | panel heading |
| `--text-body` | the knob | UI body |
| `--text-small` | per tier | metadata |
| `--text-micro` | `max(11px, small − 1px)` | the smallest thing allowed on screen |
| `--text-editor` | 15 / 17 / 19 / 21 | prose |

Tiers (小 / 中 / 大 / 特大 → `s / m / l / xl`): body 13/14/15/16, small 11/12/13/14, heading 16/18/20/22,
editor 15/17/19/21, editor line-height 1.8. `title` and `display` are anchored to `body`, not to `heading`:
heading-to-body itself varies 1.23→1.38 across the tiers, and anchoring there made the page title drift
2.34→2.61. 11px is a hard floor — Chinese below it goes soft on a normal-DPI Windows screen, and the build
used to have 8, 9, and 10px text in three places.

- UI and headings: system sans (`--font-ui`). No webfont is loaded; nothing blocks on a font request.
- Prose font is the reader's choice — 宋体 / 楷体 / 黑体 (`THEME_FONTS`), written to `--font-editor`,
  default 黑体. Serif is available in the editor, not imposed there, and it is still not allowed in page
  furniture: a serif `<h1>` in a chrome bar reads as a different product.
- Editor body: `--text-editor` with line-height 1.8, no negative tracking.
- Do not use all-caps labels as decoration. Use them only for genuine system metadata.

## Layout

- Application shell: fixed left project rail (`--rail-width: 184px`), chapter strip (`--chapters-width: 216px`),
  main column, and an inspection panel (`--right-panel-width: clamp(360px, 25vw, 430px)`) that defaults to
  **collapsed**. An open panel measured 468px of text against 720px closed, so closing is the setting the
  reading column depends on. The preference lives in `localStorage` under `myink.sidePanel` (`open`/`closed`,
  unreadable value means closed): it is "how I like to read", not "what I was last doing", so it is not
  per-project state.
- Reading column: `--measure: 720px` with `--measure-pad: 38px` of horizontal padding, folded into
  `--measure-surface` = text + padding + 1px border. Column width and padding therefore have one truth;
  the editor and the streaming preview are two states of the same column and share the same text left edge.
- Desktop content max width: `--content-max: 1280px`.
- Base spacing unit: 4px (`--space-1` … `--space-8` = 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64).
- The writing editor should occupy the largest uninterrupted region of the viewport.
- Use CSS Grid for page-level layouts. Avoid percentage-based flexbox math.
- Breakpoints are the four literals from Direction, and they answer two different questions — keep them
  separate:
  - `1200` — desktop begins to squeeze: multi-column narrows.
  - `900` — *narrowing* follows the content column: trim padding, fold side-by-side into stacked, shrink
    the rail. This is where the workspace hands the chapter strip to a horizontal row, which is what keeps
    prose near 30 characters a line on a tablet (measured 29 at 768, against 42 on a desktop width).
  - `640` — *folding* follows the rail: it becomes a top band, page roots switch to a column, secondary
    panels hide, and the lamp hides with it.
  - `420` — phone floor: dialogs go edge-to-edge, button rows may wrap, `auto-fit` grids collapse to one
    column when their own minimum is wider than the viewport.
  A stylesheet that needs none of these says so in a comment with the measurement that proves it (e.g.
  `position: fixed; inset: 0` renders at the viewport by construction, so a media query there is unwritable).

## Core Surfaces

### Project Rail

The rail provides project switching and global navigation. It uses `--rail-bg`, hairline dividers, and one
group label per section (作品 / 本书 / 全局) — a section that has to be explained by a caption is a section
that is not yet grouped. Mode (长篇 / 短篇) sits above the lists as a segmented control, deliberately a
different shape from a list row, and it is selected by inset border plus weight 650, not by the accent:
green means "you are reading this one", and only one thing can be green at a time. Interactive targets are
40px on desktop, 44px on touch; at `640` the rail folds into a top band whose ends are pinned, and the brand
mark — which is a link — is held to that same 44px so it is not the shortest thing on the strip. Do not turn
every navigation item into a card.

### Chapter Workspace

The chapter view has three clear zones: chapter navigation, the writing surface, and contextual inspection.
The editor wins visual priority. Contextual panels can show outline, recalled facts, character links,
validation findings, and generation metadata. Every one of those panels opens from a header row that is a
real touch target (40px desktop / 44px touch) — the row is the control, not a decorative band around it.
Secondary inspection panels hide entirely at `640` rather than stack into an endless scroll; if a hidden
panel owns an action available nowhere else, that action needs its own entry point.

### Writing Surface

Use `--editor` as the background and `--editor-ink` for text. The column is `--measure: 720px` of text —
about 42 汉字 per line at the default 17px, and 48 / 42 / 38 / 34 across the four reading sizes, all inside
the comfortable long-read band; the width is a constant because the size is the variable the reader controls.
Headings, paragraphs, selection, cursor, autosave state, and inline review markers must have distinct states.
Avoid placing dense controls over the text, and never let a fixed-size canvas (a world graph, an image) keep
its desktop height on a phone screen — the surface below it still has to be reachable.

### Review and Audit

Findings are listed in the workspace audit panel and on the global audit page, each with its severity, an
evidence quote, and a jump to the affected chapter. Severity uses text, color, and a 1px border together.
Never communicate a validation result by color alone.

### Generation Progress

Represent the workflow as a vertical event timeline: queued, running, waiting for review, completed, or failed. Each event can show node name, elapsed time, token/cost metadata, and a concise result. Use skeleton blocks for loading states and preserve layout dimensions.

## Components

Sizes below are the floor on the clickable element itself. Desktop 40px, touch 44px (`640` and below) — a
wrapper with padding does not count, because the hit area is the child's box, and two rows that differ only
by an invisible neighbour end up different heights.

- Primary button: `--accent` background, `--btn-primary-ink` text, `--btn-primary-border`, 8px radius, 40/44px.
- Secondary button: `--surface-2` background, `--ink` text, 1px `--btn-secondary-border` border, 8px radius.
- Quiet action: transparent background, `--ink-muted` text, visible hover surface, and no shadow — there is
  nothing there to lift.
- Danger: text and border share `--error` on a transparent background. Never leave the background unset on a
  bordered button: the UA `ButtonFace` shows through, which is `#6b6b6b` in night and fails contrast.
- Panel: `--surface-1` (opaque), 1px `--line` border, 12px radius.
- Input / textarea: `--input-bg`, 1px `--line-strong` border, 8px radius, 40/44px floor, 2px `--focus` outline.
- Range sliders: keep the native look, add the floor to the box itself — `accent-color` already paints the
  track and the knob, and the element's hit area is its own box, which the UA draws 16px tall. There is
  nothing to aim at on a phone until that box is raised.
- Status badge: compact pill only for status or severity, never for ordinary labels.
- Tabs / segmented controls: text-first with one visible active indicator. Mode uses the neutral treatment
  described under Project Rail.
- Chip / tag: 40/44px floor. Wrapping is width-driven, so raising the height changes no row counts — measure
  that before claiming it does.
- Disclosure (`<summary>`): 40/44px floor, but keep `display: list-item` — the triangle only exists there.
- Tables and timelines: use dividers and alignment; do not wrap every row in a separate card. A wide ledger
  keeps `min-width` inside `overflow-x: auto` and says so in a comment — horizontal scroll is honest for a
  table, dishonest for prose.
- Icon buttons: this product has no icon set — controls are labelled with words, and the only SVGs are the
  lamp, the progress ring, and the feedback glyph. If an icon-only control is ever added, draw it inline
  (there is no icon package or icon font in the dependency tree), give it an accessible label, and keep a
  stable 40/44px box.
- Breadcrumb / back link: 12px inline text measures 15–18px tall, so an inline link is blockified
  (`inline-flex` when it sits in a block and must not claim the whole line width, `flex` when its parent is
  already flex) before the floor is applied.

## Interaction States

Every async workflow must support queued, loading, progress, success, empty, failure, retry, and interrupted/reconnect states. Buttons need hover, focus, pressed, disabled, and pending states. Preserve user text during failures and show errors next to the relevant action.

Use motion only for hierarchy, feedback, or state transition. Respect `prefers-reduced-motion`. The interface itself must not run continuous background animations. One exception: media backgrounds a user uploads for their own theme (an animated image or a video). Such a background always carries a scrim so text stays legible, and it holds on a still frame when `prefers-reduced-motion` is set.

Every interactive element is keyboard-reachable with a visible `:focus-visible` ring, and the current
section is carried in `aria-current`, not only in a class — a mode indicator that only exists as styling
says nothing to a screen reader.

The hanging lamp is the product's one original element and, on desktop, also the feedback entry. The reader
picks among four shades (布罩 / 方灯 / 玻罩 / 喇叭, default 方灯) and the beam is on unless they turn it off.
It is decorative in shape but functional in position, and it must never eat a click: the glow and the shade are
`pointer-events: none`, one small box inside them owns the click, and at the moment of a click that box is
hit-tested against what is underneath — if an interactive control is there, the lamp yields the click to it
instead of opening. The test happens at click time, not at mount, because the content arrives asynchronously
and a rectangle measured on mount is stale a second later. Prose is not a rival: a shade over a paragraph is
what a hanging lamp does; a shade over a button is an accident. The same test runs under the pointer — reach
for a control the shade is sitting on and the shade fades to a ghost, so the accident is visible for one
instant instead of the whole session. The click yield and the fade are one rule enforced twice, and only the
shade fades: the beam is light, and light that flinches would flash the entire page.

The lamp never moves out of the way itself — on a full-bleed page there is nowhere to move to. Only the reader
moves it: a drag writes its position, kept as a fraction of the viewport (so it survives a resize) and clamped
so it cannot leave the screen, and released within 22px of the top edge it puts itself away. That is the one
lamp setting the app stores; it never rewrites the position on its own. At `640` it is hidden by the
reader's own standing preference, but hiding the lamp must not hide feedback: on that band the entry is a
labelled 反馈 button pinned to the right end of the rail (hiding the whole dock used to take the function down
with the decoration). Desktop keeps that button too, because an entry that yields clicks is not a dependable
entry. Guests get neither — submitting feedback requires a user.

## Product Screens

The first implementation should cover:

1. Project library and project switcher.
2. Work dashboard showing recent chapters, pending reviews, and generation status.
3. Chapter editor with outline, editor, and contextual inspection.
4. Generation progress timeline with reconnect and failure states.
5. Audit report with evidence, severity, and chapter navigation.
6. Characters, world rules, facts, relationships, and foreshadowing views.

## Quality Rules

- The primary action is obvious without relying on color alone.
- Text never overlaps, clips, or shifts the layout when state changes.
- All controls have keyboard focus states and mobile touch targets of at least 44px.
- Avoid generic three-card feature grids, excessive rounded containers, purple AI gradients, and decorative metrics.
- Use real workflow data in previews. Do not use placeholder names such as `Acme` or `Jane Doe`.
- Verify desktop and mobile layouts, loading states, error states, and long Chinese text before shipping.
