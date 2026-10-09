---
name: prep-a-fight
description: Prepare a raid boss in minutes, from the top players' logs and sims on the real fight.
colors:
  vintage-grape: "#5c415d"
  vintage-grape-2: "#694966"
  dusty-lavender: "#74526c"
  golden-sand: "#dbd053"
  golden-bronze: "#c89933"
  bg-light: "#f6f2f5"
  surface-light: "#ffffff"
  surface-2-light: "#f1eaf0"
  line-light: "#e3d8e1"
  fg-light: "#2a1f2b"
  muted-light: "#6f5c6d"
  accent-soft-light: "#f6efd2"
  bg-dark: "#181219"
  surface-dark: "#221a23"
  surface-2-dark: "#2b212c"
  line-dark: "#3b2e3c"
  fg-dark: "#f2eaf1"
  muted-dark: "#b6a3b3"
  accent-soft-dark: "#3a3320"
  pos-light: "#2f7d3e"
  neg-light: "#b3392e"
  warn-light: "#9a6a10"
  pos-dark: "#8fd18b"
  neg-dark: "#f08f84"
  warn-dark: "#e7c35a"
  rarity-green: "#1eff00"
  rarity-blue: "#0070dd"
  rarity-purple: "#a335ee"
typography:
  display:
    fontFamily: "Chakra Petch, Bahnschrift, Segoe UI, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "0.005em"
  headline:
    fontFamily: "Chakra Petch, Bahnschrift, Segoe UI, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    letterSpacing: "0.06em"
  title:
    fontFamily: "Chakra Petch, Bahnschrift, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    letterSpacing: "0.01em"
  body:
    fontFamily: "IBM Plex Sans, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Chakra Petch, Bahnschrift, Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.08em"
  data:
    fontFamily: "IBM Plex Mono, Consolas, ui-monospace, monospace"
    fontSize: "32px"
    fontWeight: 700
    fontFeature: "tnum"
rounded:
  sm: "5px"
  md: "8px"
  lg: "10px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.vintage-grape}"
    textColor: "{colors.surface-light}"
    rounded: "{rounded.lg}"
    padding: "9px 16px"
  button-primary-dark:
    backgroundColor: "{colors.golden-bronze}"
    textColor: "#1c1410"
    rounded: "{rounded.lg}"
    padding: "9px 16px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.fg-light}"
    rounded: "{rounded.lg}"
    padding: "9px 16px"
  card:
    backgroundColor: "{colors.surface-light}"
    rounded: "{rounded.lg}"
    padding: "16px 18px"
  chip:
    backgroundColor: "{colors.surface-2-light}"
    rounded: "{rounded.pill}"
    padding: "7px 12px"
  chip-selected:
    backgroundColor: "{colors.accent-soft-light}"
    rounded: "{rounded.pill}"
    padding: "7px 12px"
  pill:
    backgroundColor: "{colors.surface-2-light}"
    textColor: "{colors.muted-light}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  input:
    backgroundColor: "{colors.surface-2-light}"
    textColor: "{colors.fg-light}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
---

# Design System: prep-a-fight

## Overview

**Creative North Star: "The Night Before the Pull"**

The app is opened in the calm before a raid night: a few minutes with a boss sheet, then the pull. The system carries that hour. Deep grape and plum night tones hold the structure, a soft violet glow sits behind the page, and gold is kept for what matters on this boss: the key number, the selected choice, the line to remember. The dark theme is the signature look; the light theme gets the same care and the same hierarchy, never an inversion.

It is calm and reassuring rather than loud. A casual raider should feel the page is on their side: plain sentences first, the details folded, nothing that shouts. The game is present in the details, not in costume: the display face has a slight angular, HUD-like cut, difficulty uses the game's rarity colors and shapes, and the whole app takes the class color of the active character.

Density is moderate: one column of readable prose (68 to 80 characters) with data blocks that align on tabular figures.

**Key Characteristics:**
- Night tones for structure, gold for emphasis, the class color as the active character's signature.
- Sentences before numbers; tables and raw data are folded details.
- Surfaces sit lightly above a glowing ground (soft shadow, slight blur).
- Gently rounded, pill-shaped controls; one filled button per screen.
- Every color that carries meaning also carries a label or a shape.

## Colors

A night palette of grapes and lavender with two golds, plus the game's own class and rarity colors.

### Primary
- **Vintage Grape** (`vintage-grape`): the structure. The header gradient (with Vintage Grape 2 and Dusty Lavender), primary buttons and links in the light theme.
- **Golden Bronze** (`golden-bronze`): the default accent in the light theme (focus rings, selected chips, the hero's edge, checkboxes) and the primary button fill in the dark theme.
- **Golden Sand** (`golden-sand`): the dark theme's accent and links, the active tab, the "fight" in the wordmark.

### Secondary
- **Class color** (runtime `--class`, from the game's class colors): when a character is active, it replaces the accent (darkened to 68% on light, lightened to 82% on dark so it reads on both) and the header's stripe. It names who is being prepared.

### Tertiary
- **Rarity Green / Blue / Purple** (`rarity-green`, `rarity-blue`, `rarity-purple`): difficulty only (normal, heroic, mythic), always paired with a shape: triangle, square, pentagon.

### Neutral
- **Plum paper / Night plum** (`bg-light` / `bg-dark`): the page ground, under the violet-and-gold glow.
- **Surface** (`surface-light` / `surface-dark`) and **Surface 2** (`surface-2-light` / `surface-2-dark`): cards and tiles; inputs, chips and code.
- **Line** (`line-light` / `line-dark`): every border and table rule.
- **Ink** (`fg-light` / `fg-dark`) and **Muted** (`muted-light` / `muted-dark`): body text; secondary text, section headings, table headers.
- **Status** (`pos-*`, `neg-*`, `warn-*`): gains, losses, warnings; a sign or a word always says the same thing.

### Named Rules
**The Gold Is Rare Rule.** Gold marks the one thing to see on a block: a key number, a selection, a focus. It is never body text on a light background (too little contrast).

**The Class Signs Rule.** The class color stands for the active character and nothing else; it never encodes data.

## Typography

**Display Font:** Chakra Petch (with Bahnschrift, Segoe UI)
**Body Font:** IBM Plex Sans (with Segoe UI, system-ui)
**Label/Mono Font:** IBM Plex Mono (with Consolas)

**Character:** A slightly angular display face for headings, buttons and labels, a sober humanist sans for reading, and a mono with tabular figures for the numbers. The game's edge, kept to the headings.

### Hierarchy
- **Display** (700, 30px, 1.15; 22px under 640px): the page title, usually the boss name with its difficulty pill.
- **Headline** (600, 17px, uppercase, 0.06em, muted): section headings. Quiet signposts, not shouts.
- **Title** (600, 16px): card and block titles.
- **Body** (400, 15px, 1.6): sentences, held to 68ch for the lead and 80ch otherwise.
- **Label** (600, 11 to 12px, uppercase, 0.05 to 0.08em): pills, table headers, KPI labels.
- **Data** (700, 32px, tabular): key figures; every aligned number uses tabular figures.

### Named Rules
**The Sentence First Rule.** A block opens with what to do, written as a sentence; the numbers follow and support it.

## Layout

A single centered column (max 1040px, 16px side gutters, 24px top and 48px bottom) under a full-width header. Blocks flow vertically with 10 to 14px between cards and 34px above a section heading. Tiles use an auto-filling grid (cells of 220px minimum, 12px gap); controls sit in wrapping rows with 8 to 10px gaps. Under 640px the title shrinks, labels in the header collapse to icons and grids fall to one column. Wide tables scroll inside their own container, never the page.

## Elevation & Depth

A light relief. The ground is lit by two soft radial glows (violet top left, gold top right) fixed behind the page. Cards and tiles sit just above it: a near-transparent surface (92%) with a 4px backdrop blur and a soft two-layer shadow. Hover lifts a link tile by 2px. Nothing floats higher than that.

### Shadow Vocabulary
- **Surface** (`0 1px 2px rgba(42,31,43,.06), 0 4px 16px rgba(42,31,43,.06)`; dark: `0 1px 2px rgba(0,0,0,.3), 0 6px 20px rgba(0,0,0,.25)`): cards, tiles, the hero.
- **Accent halo** (`0 0 0 3px` accent at 30%): button hover.

### Named Rules
**The Objects Only Rule.** A shadow marks an object (a card, a tile); sections, lists and text never get one.

## Shapes

Gently rounded throughout: 10px for cards, tiles and buttons, 8px for inputs and notices, 5 to 6px for code and focus rings, full pills for chips, tags and header buttons. Circles number the steps. The only sharp geometry is the difficulty frames: a triangle, a square and a pentagon, cut with clip-paths around the boss portraits.

## Components

### Buttons
Clear and reassuring; one filled button per screen.
- **Shape:** gently rounded (10px), display font, 600, 0.03em tracking.
- **Primary:** Vintage Grape with white text on light; Golden Bronze with near-black text on dark (9px 16px; big: 12px 22px, 16px).
- **Hover / Focus:** a 3px accent halo and a slight brightening; 1px press on active; 2px accent focus ring offset 2px.
- **Ghost:** transparent with a line border, for the secondary actions.

### Chips
- **Style:** pills on Surface 2 with a line border, 14px text, an optional muted meta.
- **State:** selected (a checked input inside) turns the border to the accent and the fill to Accent Soft.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** Surface at 92% over the glow, 4px blur.
- **Shadow Strategy:** the Surface shadow (see Elevation).
- **Border:** 1px Line.
- **Internal Padding:** 16px 18px (tiles 14px 16px).
- **Hero:** the verdict block, with a 5px accent edge on the left and a 20px bold verdict line.

### Inputs / Fields
- **Style:** Surface 2 fill, 1px Line, 8px corners, 8px 10px padding.
- **Focus:** 2px accent outline, offset 1px.

### Navigation
- **Header:** a grape gradient band with a 3px gold (or class color) stripe at the bottom; the wordmark "prep-a-**fight**" with "fight" in Golden Sand; Back and Home as translucent white pills; the active character's menu; nav links as 8px-rounded items that fill with white at 14% when active or hovered.
- **Tabs (prep sheet):** a darker band under the header, 14px semibold labels, the active tab in Golden Sand with a 3px underline.

### Raid board (signature)
The bosses of the raid in a row, in the Encounter Journal order, as portraits without a background; a boss not prepared is greyed out. On hover, the three difficulties appear as the same portrait framed by a green triangle (normal), a blue square (heroic) and a purple pentagon (mythic), each with its state in words (prepared, to redo, running).

### Steps and KPIs
Numbered steps in accent-ringed circles; KPI tiles with an uppercase label, a large tabular value and a muted note.

## Do's and Don'ts

### Do:
- **Do** take every color from the tokens, in both themes, and the accent from the active character's class when there is one.
- **Do** open each block with a sentence and fold the tables in `details`.
- **Do** pair every color that means something with a word or a shape (difficulty, gain or loss, state).
- **Do** use tabular figures for every number that lines up.
- **Do** respect reduced motion: transitions off, the minute view as plain sections.

### Don't:
- **Don't** set body text in gold on a light background.
- **Don't** use the class color or the rarity colors for anything but the character and the difficulty.
- **Don't** put more than one filled button on a screen.
- **Don't** give a shadow to anything but a card or a tile.
- **Don't** add a style block in a module for something the theme already defines.
