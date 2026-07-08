# Metal Halftone Studio — Specification (v1)

A standalone tool for previewing and generating **silicon-die metal-layer "halftone"
artwork** for chip tapeouts on the **GF180MCU** PDK (targeting wafer.space fabrication
slots). You paint a **color control image**, and the tool renders it as a **DRC-clean,
1-bit metal stencil** and emits a placeable **GDSII "art macro"** ready to drop into a
LibreLane / wafer.space chip flow.

This document is self-contained and implementation-ready. An engineer should be able to
build the tool from this spec without further questions. It generalizes an existing
working prototype (`ip/eurosynth_art/script/make_gds.py` and its macro views) into a
reusable, configurable studio with a live browser preview.

---

## Table of contents

1. [Overview: goals & non-goals](#1-overview-goals--non-goals)
2. [Background: why 1-bit, why on-grid, the DRC constraints](#2-background-why-1-bit-why-on-grid-synthesis-the-drc-constraints)
3. [The control-map color system (locked v1)](#3-the-control-map-color-system-locked-v1)
4. [The rendering / synthesis pipeline](#4-the-rendering--synthesis-pipeline)
5. [Components & architecture](#5-components--architecture)
6. [Macro packaging (four GDS views)](#6-macro-packaging-the-four-macro-views)
7. [File formats & conventions](#7-file-formats--conventions)
8. [Build & DRC workflow](#8-build--drc-workflow)
9. [Repo structure, dependencies & roadmap](#9-repo-structure-dependencies--roadmap)
10. [Glossary](#10-glossary)

---

## 1. Overview: goals & non-goals

### What it is

**Metal Halftone Studio** turns an ordinary color image (a "control map") into a
manufacturable piece of on-die artwork rendered in the chip's **metal layers**. Because
metal on silicon is binary — a spot is either metal or bare silicon, there is no
grayscale — apparent "shading" is produced by a **halftone screen**: a regular pattern of
metal lines/dots at a legal pitch, whose local coverage encodes tone. The studio's core
promise:

> **Paint in colors → get a DRC-clean metal-art GDS.**

Each painted region's **color (hue)** selects a screen *style* (lines / mesh / dots / at
various angles), and its **saturation / lightness** selects the screen *density* (how
much metal, i.e. how dark it reads). Black paints solid metal; white paints bare silicon.

### Who it's for

Chip artists and hardware engineers preparing **tapeout artwork** — a logo, wordmark,
mascot, or decorative graphic placed in the open area of a die so it shows up in a die
photo. The typical user is comfortable with images and wants a bold, legible graphic on
silicon *without* becoming a DRC expert or hand-editing polygons.

### Goals

- Take a color **control image** (PNG/RGBA) and produce a **1-bit metal stencil** that
  passes GF180MCU metal DRC (BEOL) with **zero real violations**.
- Provide a **CLI** (`make art`) that generates the GDS deterministically from a control
  image + a config file.
- Provide a **live browser preview** so the artist iterates on look and coverage *before*
  the (slow) Docker/DRC round-trip — the preview draws the *same* on-grid screens the core
  library emits, so what you see matches what you get.
- Emit the **four macro views** (`gds` / `lef` / `lib` / `vh`) needed to place the art in a
  chip flow as an inert obstruction black box.
- Be reproducible on a machine with **no native EDA tools** — generation and DRC run in
  throwaway Docker containers.

### Non-goals

- **Not** a full chip-integration tool. It produces the art macro; placing it, dummy-fill,
  and final chip signoff happen in the host chip flow (see §6).
- **Not** photo-realistic. Halftone gives ~6 discrete "shades" per style at best; design
  for bold graphics, not photographs.
- **Not** a general raster editor. The user paints the control map in *any* image editor;
  the studio interprets it. (The browser preview offers only light painting for tweaking.)
- **Not** multi-PDK (v1). It is specialized to GF180MCU's 5-metal stack and DRC deck.
  Layer maps and DRC numbers are parameterized enough to port later, but that is out of
  scope for v1.

---

## 2. Background: why 1-bit, why on-grid synthesis, the DRC constraints

### 2.1 Why 1-bit (metal has no grayscale)

A metal layer is a mask: at every point it is either **present** (drawn) or **absent**.
There is no "50% metal." So the only way to render a *tone* is a **halftone screen** — a
fine, regular pattern (parallel lines, a grid mesh, or a dot array) whose **fraction of
area covered by metal** encodes the tone. From arm's length the eye integrates the pattern
into a shade; up close it is crisp lines/dots. This is exactly how newspaper printing
renders gray with black ink on white paper. Our "ink" is metal; our "paper" is bare
silicon.

Consequence: **every output pixel is 0 or 1.** All shading is pattern, never a gray value.

### 2.2 Why the screen must be synthesised ON the metal grid

The single most important hard-won fact in this tool:

> **The halftone screen MUST be synthesised directly on the metal grid at a legal pitch.
> You must NOT downscale a pre-rendered / pre-dithered halftone image onto the grid.**

If you take an image that has *already* been dithered/screened at some arbitrary
resolution and then resize it down onto the metal pixel grid, the resampling **shatters
the pattern into sub-minimum slivers** — fragments narrower than the minimum metal width,
diagonal one-pixel bridges, and one-pixel gaps. These are all DRC violations.

This is not theoretical. Measured on the prototype: a single **dithered gear image**
downscaled onto the grid produced **503,097 DRC violations**. The *same gear*, with its
screen **synthesised on-grid at pitch ≥ ~3 µm**, was DRC-clean.

The rule that follows: **resize the source FIRST to the target grid resolution, then
synthesise the screen at that resolution** so every metal feature and gap lands on the
grid at a controlled, legal width. (See `_control_halftone` / `_halftone` in the
prototype: the source is `resize(...)`d *before* the screen loop runs.)

### 2.3 The DRC constraints (GF180MCU metal / BEOL)

These are the metal-layer rules the output must satisfy. "px" below is a grid pixel;
its physical size is `pixel_size` µm (see §4). All figures are µm.

| Rule | Metal1 | Metal2–Metal5 | Notes |
|---|---|---|---|
| **Min width** | 0.23 | 0.28 | Narrowest legal metal shape. A screen line/gap thinner than this fails. |
| **Min space** | 0.23 | 0.28 | Narrowest legal gap between two metal shapes. |
| **Min metal area** | 0.1444 µm² | 0.1444 µm² | Smallest legal isolated metal island (≈ 0.38 µm square). |
| **MSLOT.1 (stress-relief slots)** | applies | applies | A metal region that is **≥ ~30 µm in BOTH dimensions** ("wide metal") must contain **stress-relief slots** (holes). The binding measure is the region's **short dimension**: long + thin is fine (a 5 µm × 400 µm strip passes), square-ish + big fails (~30 × 30 µm pad). The screen inherently slots the art (it always leaves grid gaps); a large *solid* region (black paint) is the one thing that trips it — see the **wide-metal guard, §4.8**. DRC-verified on the eurosynth art macros (gf180mcuD, `beol=true`, 2026-07-03). |
| **Die metal coverage** | > 30% | > 30% | The whole die (not this macro) must be at least ~30% metal. This is a **benign die-level rule** satisfied by **dummy metal fill** at chip integration, *not* by the art macro. Ignore it when DRC'ing the art in isolation (see §8). |
| Acute angles / off-grid | — | — | Manhattan (axis-aligned) geometry only in v1. Diagonal screens rasterised as pixel staircases create tiny acute wedges that risk min-width/notch violations — see §4.6. |

Design implications baked into the pipeline:

- Every **feature** (a screen line/dot) and every **gap** must be **≥ 2 px** so that after
  the morphological cleanup they clear min-width and min-space. At the default
  `pixel_size = 0.60 µm`, 2 px = 1.2 µm — comfortably above the 0.23/0.28 floors.
- A recommended **screen pitch ≥ ~3 µm** (≈ 5 px at 0.60) gives room for a ≥2 px feature
  and a ≥2 px gap simultaneously.
- The screen never goes 100% solid (`_feat` caps feature width at `screen − 2`), so there
  are always grid gaps — this is the art's built-in slotting for MSLOT.1. **Solid (black)
  regions are the exception**: they bypass the screen entirely, so the pipeline must apply
  the **wide-metal guard** (§4.8) — never emit a solid component wider than ~28 µm in its
  short dimension.

---

## 3. The control-map color system (locked v1.2)

> **v1.1 change log:** grey now maps to **clustered dots** (the classic photo
> halftone) instead of horizontal lines, rendered via the **threshold matrix**
> (§4.4) for ≈ `P²` tone levels instead of `_feat`'s 2–3; **blue** takes the freed
> **horizontal lines**; two new Manhattan-safe styles are added — **orange → brick
> (running bond)** and **violet → basket weave**. Red/yellow/green/cyan/magenta are
> unchanged.
>
> **v1.2 change log:** "solid" no longer emits literal solid metal — it renders as
> **auto-slotted solid**: full fill minus one **2×2 slot hole per `dot_pitch` cell**
> (density `1 − 4/dot_pitch²` ≈ **96%** at the default 10 px), i.e. exactly the
> darkest grey tone, so black is self-slotting and immune to the wide-metal rule
> (§4.8). Grey's threshold matrix gets its own **`dot_pitch`** cell size (default
> `2 × pitch` = 10 px), decoupled from the screen pitch: light greys start at a
> single 2×2 dot per cell (4% coverage at 10 px, vs 16% at 5 px), the density floor
> drops from the fixed ~0.15 to the seed minimum `4.5 / dot_pitch²`, and the tone
> curve is **capped** at the slotted maximum `1 − 4/dot_pitch²` — near-black grey
> can no longer close into unslotted wide metal.

The heart of the tool. The user paints a **control image** where each region's **color**
encodes *how to screen it*. Detection is done in **HSV** (each channel treated as 0–1
below; if your library gives 0–255, scale accordingly — the prototype uses 0–255 and the
same thresholds).

### 3.1 Locked v1 classification

Given a pixel's HSV `(H in degrees 0–360, S in 0–1, V in 0–1)`:

| Class | Condition | Screen style | Density source |
|---|---|---|---|
| **Solid metal** | `V < 0.28` **and** `S < 0.35` (black) | **Auto-slotted solid** — full fill minus a **2×2 slot hole per `dot_pitch` cell** (= the darkest grey tone; §4.4, §4.8) — v1.2, never literal solid | density = `1 − 4/dot_pitch²` (≈ 0.96 at 10 px) |
| **Empty** (bare Si) | `V > 0.90` **and** `S < 0.12` (white) | — (no metal) | n/a (density = 0.0) |
| **Grey** | `S < 0.12` **and** `0.28 ≤ V ≤ 0.90` | **Clustered dots (threshold matrix)** | `density = (0.90 − V) / (0.90 − 0.28)`, clamped to `[4.5/dot_pitch², 1 − 4/dot_pitch²]` (darker grey = bigger dots; the cap keeps a 2×2 slot hole in the darkest cell). Rendered via the **clustered-dot threshold matrix** (§4.4) on its own `dot_pitch` cell (default `2 × pitch`), not `_feat` width quantization — ≈ `dot_pitch²` tone levels per cell, so greyscale photos/gradients shade smoothly |
| **Colored** | `S ≥ 0.12` **and** `V ≥ 0.28` | chosen by **hue** (table below) | `density = clamp(S / 0.55, 0.2, 1.0)` (more saturated = denser; pale pastels still render a visible screen) |

**Colored: hue → screen style** (only reached when `S ≥ 0.12` and `V ≥ 0.28`):

| Hue range (°) | Color name | Screen style | Angle / pattern |
|---|---|---|---|
| 340–360 and 0–20 | **Red** | Diagonal **X-mesh** | 45° + 135° crosshatch |
| 20–45 | **Orange** | **Brick** | running bond (offset courses) |
| 45–75 | **Yellow** | Diagonal lines | 45° ("/") |
| 75–150 | **Green** | **Mesh grid** ("#") | horizontal + vertical |
| 150–200 | **Cyan** | Diagonal lines | 135° ("\") |
| 200–250 | **Blue** | Horizontal lines | 0° ("−") |
| 250–290 | **Violet** | **Basket weave** | cells checker between H and V stripes |
| 290–340 | **Magenta** | Vertical lines | 90° ("\|") |

**Density mapping detail:**

- **Grey → clustered dots.** Tone comes from *lightness*: a mid-grey renders sparse dots;
  near-black grey renders fat, near-touching ones — exactly how a newspaper photo shades.
  Floor at `4.5 / dot_pitch²` (≈ 0.045 at the default `dot_pitch = 10`) — exactly enough
  density to place the smallest cleanup-surviving dot (the 2×2 seed, §4.4) in every cell,
  so even the lightest grey shows *some* metal (otherwise light grey and white become
  indistinguishable) while staying as sparse as physically possible.
- **Colored → hue-selected style.** Tone comes from *saturation*: `density = clamp(S/0.55,
  0.2, 1.0)`. Dividing by 0.55 means a fully saturated color (S = 1) clamps to max density,
  while a **pale pastel** (say S = 0.2) still yields `density ≈ 0.36` — a visible screen,
  not a near-empty one. The 0.2 floor guarantees any colored region reads as *some* metal.

### 3.2 Described legend (what to paint)

Think of the control map as a **paint-by-style** sheet. A quick mental legend:

```
  BLACK            -> solid metal, auto-slotted (tiny 2x2 hole per cell; v1.2)
  WHITE            -> bare silicon (nothing drawn)
  GREY (light..dark) -> clustered-dot shading, light->dark = small->fat dots  ....

  RED    -> X-crosshatch  (45 + 135)      ####  (densest-looking)
  ORANGE -> brick         (running bond)  ▄▄▀▀
  YELLOW -> "/" lines     (45)            ////
  GREEN  -> "#" mesh grid (H + V)         ++++
  CYAN   -> "\" lines     (135)           \\\\
  BLUE   -> "-" lines     (0 horizontal)  ----
  VIOLET -> basket weave  (H/V checker)   ▤▥▤▥
  MAGENTA-> "|" lines     (90 vertical)   ||||

  Within a color: MORE SATURATED = DENSER (more metal).
  Within grey:    DARKER          = DENSER (bigger dots).
```

Rationale for the hue assignments: the six primary/secondary hues (R, Y, G, C, B, M) plus
orange and violet are easy to pick unambiguously in any paint program. Grey takes the
clustered dot — tonal shading *is* what dots are for, and photos/gradients naturally arrive
as greyscale. Warm colors (red/yellow) lean to diagonal energy with orange's brick between
them; green/magenta anchor the orthogonal H/V family, blue joins it with plain horizontals,
violet mixes the two as a weave; cyan takes the opposite diagonal.

### 3.3 Line-art rule

Near-black stays **solid and crisp** — this preserves logos, wordmarks, and outlines as
sharp metal. Only **mid-tones and colors** get screened. **White is empty.** So a
black-line drawing on a white background comes through as clean solid line-art with no
screening, exactly as drawn.

### 3.4 How to extend the color system (adding hues/styles)

The mapping is a **lookup by hue band → (style, angle)**. To add a style:

1. **Pick an unused hue band.** The eight bands above cover the wheel with no gaps, so
   extending means *subdividing* a band (e.g. split Green 75–150° into "green = mesh
   coarse" 75–110° and "spring = mesh fine" 110–150°) or introducing a
   **second axis** (e.g. use *value* within a colored region to select coarse vs. fine
   pitch, since value is otherwise only gating "is it colored at all").
2. **Add the style's on-grid generator** (a boolean `metal(x, y, pitch, width)` function,
   see §4.4) to the core library's style registry.
3. **Register it in one table** shared by the core library *and* the browser preview so the
   two never diverge. This table is the single source of truth (see §5, config
   `style_registry`).
4. **Re-validate with DRC**, especially for any new diagonal/rotated style (see §4.6).

Keep v1.2's styles **locked** as the documented, tested defaults; extensions are
additive and must not change v1.2 behavior.

---

## 4. The rendering / synthesis pipeline

The pipeline transforms a control image into a 1-bit, DRC-clean, on-grid stencil, then
into GDS polygons. Order matters.

```
control PNG (RGBA)
   │  paste over white using ALPHA as mask   (§4.1 — gotcha)
   ▼
RGB image
   │  resize to target grid (W×H px) FIRST   (§2.2 — on-grid rule)
   ▼
per-pixel classify  (HSV → style, density)   (§3, §4.3)
   │
   ▼
per-pixel on-grid screen synthesis           (§4.4)   metal = 0 (black), empty = 255
   │
   ▼
2×2 morphological OPEN   (_open2)             (§4.5)  removes sub-2px edge slivers
   │
   ▼
DECLOBBER   (_declobber)                      (§4.5)  breaks diagonal corner pinches
   │
   ▼
1-bit stencil  ('1' image, metal = 0)
   │  each metal pixel → pixel_size µm square, on 5 metal layers + boundary box
   ▼
GDSII  (klayout.db)                           (§4.7)
```

### 4.1 Source ingestion (the ALPHA gotcha — do not skip)

**Critical gotcha:** the ingestion step pastes the source over a solid **white** RGBA
background *using the source image's ALPHA channel as the paste mask* (mirroring the
prototype's `new_image.paste(img, (0,0), img)`). Therefore:

- The source **must have a real alpha channel.** An opaque **RGBA** image is fine (alpha
  all 255 → the whole image pastes).
- A plain **L or RGB** image with *no* alpha channel gets treated as an all-zero mask and
  **the paste blanks the image to white** (→ everything reads as "empty"). This is a silent
  failure mode.

**Requirement:** the ingestion code MUST **force an alpha channel** — e.g.
`img = Image.open(path).convert("RGBA")` (which fills opaque alpha for L/RGB sources) —
before the paste, and the CLI/preview MUST warn if the loaded control image had no alpha.

(For the historical threshold/silhouette path an `--invert-alpha` variant pastes over
black instead; v1's control-map path always uses white.)

### 4.2 Resize first (on-grid)

Compute the target grid size in pixels and resize the source to it **before** screening:

```
grid_px_w = round(desired_um_w / pixel_size)      # e.g. 480 µm / 0.60 = 800 px
grid_px_h = round(desired_um_h / pixel_size)
source_resized = source_rgb.resize((grid_px_w, grid_px_h), LANCZOS)
```

All subsequent per-pixel work happens at this resolution so features land on-grid (§2.2).

### 4.3 Classify

For each pixel, convert to HSV and apply §3.1 to get `(style, density)`:

- `style ∈ {solid, empty, hline, vline, d45, d135, mesh, xmesh, dot, brick, weave}`
- `density ∈ [0, 1]`

### 4.4 On-grid screen synthesis (the pixel formulas)

Let `P` = screen pitch in px (`screen` in the prototype), and `w = _feat(density, P)` the
feature width in px. `metal` is `True` where metal is drawn.

**Feature-width mapping `_feat(density, P)`** — map density to an on-grid width where both
the feature *and* its complementary gap stay ≥ 2 px (so both survive the 2×2 open and clear
min-width/min-space), never fully solid:

```
lo, hi = 2, max(2, P - 2)
w = clamp(round(lo + density * (hi - lo)), lo, hi)
```

**Per-style boolean generators** (all take pixel coords `(x, y)`, pitch `P`, width `w`):

| Style | Formula |
|---|---|
| **hline** (horizontal, 0°) | `(y % P) < w` |
| **vline** (vertical, 90°) | `(x % P) < w` |
| **d45** ("/", 45°) | `((x + y) % P) < w` |
| **d135** ("\", 135°) | `((x - y) % P) < w` (use `(x - y) mod P`, handle negatives) |
| **mesh** ("#", H+V) | `((y % P) < w) or ((x % P) < w)` |
| **xmesh** (X, 45+135) | `(((x + y) % P) < w) or (((x - y) % P) < w)` |
| **dot** (clustered) | see below |
| **brick** (running bond) | `off = P if (y // P) odd else 0`; `((y % P) < w) and (((x + off) % 2P) < 2P − (P − w))` — courses `w` tall, mortar `P − w` (≥ 2 px by `_feat`), head joints offset half a brick per course |
| **weave** (basket) | `(x % P) < w` if `((x // P) + (y // P))` odd else `(y % P) < w` — cells checker between vertical and horizontal stripes |
| **solid** | v1.2: **auto-slotted** — `not ((x mod Pd ≥ Pd−2) and (y mod Pd ≥ Pd−2))`, i.e. full fill minus a 2×2 slot hole at each `dot_pitch` cell's far corner (identical to the darkest grey tone). **Never** `True` across a region, so black cannot trip MSLOT (§4.8). Literal fill only via config `solid_fill: true` + the §4.8 guard. |
| **empty** | `False` |

**Dots (clustered-dot).** A dot centered in each `P×P` cell, of side `w`:

```
cx, cy = x % P, y % P
lo = (P - w) // 2
metal = (lo <= cx < lo + w) and (lo <= cy < lo + w)
```

**Threshold-matrix form (REQUIRED for grey, v1.1).** The square-dot form quantizes tone
through `_feat`, which at the default pitch 5 allows only widths {2, 3} — i.e. **two**
grey levels. Grey therefore renders via a **clustered-dot threshold matrix** `T`
(prototype `_halftone` builds one): sort the `Pd²` cell positions by distance from the
cell center, assign ascending thresholds `T[i][j] = (rank + 0.5)/Pd²`, then
`metal = density > T[y % Pd][x % Pd]`. The dot grows one grid pixel per tone step —
**≈ `Pd²` grey levels per cell** (25 at pitch 5, 100 at pitch 10), which is what makes
greyscale photos and gradients shade photographically.

**`Pd` is `dot_pitch`, the matrix's own cell size (v1.2)** — decoupled from the screen
pitch `P`, default `dot_pitch = 2 × pitch` (10 px = 6 µm at the default recipe). The
minimum dot is fixed at 2×2 px by the cleanup pass, so **cell size is the only sparseness
lever**: the lightest tone is one 2×2 seed per cell = `4 / Pd²` coverage — 16% at
`Pd = 5`, **4% at `Pd = 10`**, 1% at `Pd = 20`. Larger `Pd` = sparser lights, more tone
levels, but chunkier dark-grey dots (a 0.9-density dot at `Pd = 20` is ~19 px ≈ 11 µm —
still short-dim safe, §4.8). The grey **density floor is derived, not configured**:
`floor = 4.5 / Pd²`, the smallest density that turns on the full seed.

**Global grey tone curve (v1.2).** Adjusting greys per source shade is cumbersome, so
an optional global curve reshapes every *auto* grey density before clamping (per-color
overrides bypass it):

```
d' = (d^gamma − 0.5) · contrast + 0.5 + brightness      # defaults (1, 1, 0) = identity
d' ≤ 0 → empty (no dots);  otherwise clamp to [4.5/Pd², 1 − 4/Pd²]
```

`gamma` bends the mid-tones (photographic lightening/darkening), `contrast` steepens the
curve about mid-grey, `brightness` shifts the whole range — and can push the lightest
greys to bare silicon or the darkest to the slotted maximum. Config: `grey_tone` (§7.3);
the browser preview exposes all three as live sliders.

**The dark end is capped and slot-seeded (v1.2).** When building the ranking, the
**far-corner 2×2 block** (`x, y ∈ [Pd−2, Pd−1]`) is forced to rank *last* regardless of
distance, and density clamps to `d_max = 1 − 4/Pd²`. Result: the darkest tone is full
metal minus one **2×2 slot hole per cell** — dark greys grow monotonically toward it but
can **never close into unslotted solid**. "Solid" (black) renders exactly this `d_max`
pattern (§3.1), so black = the darkest grey and both are MSLOT-safe by construction
(holes every `Pd` px = 6 µm at defaults, far under the ~28 µm window of §4.8). Since the
holes tile at each cell's far corner, adjacent cells keep them on a regular `Pd` grid.

Two DRC details of the matrix form:

- **Seed the ranking off-center by a quarter pixel** (rank by distance from
  `((Pd−1)/2 − 0.25, (Pd−1)/2 − 0.25)`), so ranks 0–3 form a **2×2 block**. A ranking
  centered on a single pixel starts the dot as 1–3 px fragments, which the 2×2 open
  (§4.5) deletes — light greys would silently render empty. With the 2×2 seed, the
  derived density floor (`4.5 / Pd²`) lands exactly on the smallest dot that
  survives cleanup.
- Intermediate growth stages can carry 1-px nubs; the standard §4.5 open + declobber
  passes shave them, which slightly quantizes the tone curve but keeps it monotonic.

The square-dot form (`w×w` block, density via `_feat`) remains available as the `dot`
style for hue-mapped extensions, where per-region tone is flat and 2–3 steps suffice.

> **Note on diagonals (`d45`, `d135`, `xmesh`, and yellow/cyan/red styles):** the modulo
> formulas above produce **pixel staircases**, not true diagonals. This is acceptable as a
> first cut but is the main DRC risk area — see §4.6 for the robust true-polygon approach.

### 4.5 Cleanup: 2×2 open, then declobber

Two morphological passes make the on-grid screen DRC-clean. Operate on an `L` image where
**metal = 0 (black), empty = 255**.

**`_open2` — 2×2 morphological opening.** Removes sub-2px slivers (e.g. where a screen line
meets a curved, anti-aliased edge), so no feature is thinner than ~2 px and no acute
1-pixel spur survives:

```
erode metal by max/"lighter" over offsets (-1,0), (0,-1), (-1,-1)
then dilate by min/"darker" over offsets (+1,0), (0,+1), (+1,+1)
```

(Erode-then-dilate = opening; on a metal=0 image, "erode metal" is a *lighten* and "dilate"
is a *darken* via shifted-image compositing — see the prototype's `ImageChops.lighter` /
`ImageChops.darker` construction.)

**`_declobber` — break diagonal corner-touches.** After the open, curved/anti-aliased
edges can still leave **2×2 checkerboards**: metal on one diagonal, empty on the other. A
**metal–metal diagonal contact is a zero-width pinch** (min-width violation) and the
**complementary empty–empty diagonal is a zero-space pinch** (min-space violation).
Filling *one* corner removes *both* at once:

```
for each 2x2 block (a b / c d):
    if a==metal and d==metal and b==empty and c==empty:  set b = metal
    elif b==metal and c==metal and a==empty and d==empty: set a = metal
(run 2 passes)
```

**Why this is required:** without declobber, mesh/dot styles on curved art measured
**30–44 min-width violations per metal layer**. With it, they go to zero. It is not
optional for dot/mesh/curved art.

### 4.6 Diagonals: the true-polygon recommendation

Rendering `d45`/`d135`/`xmesh` as **pixel staircases** (§4.4) creates a jagged edge of tiny
axis-aligned steps. Each step is a small notch/spur; on curved art some steps drop below
min-width or create near-acute wedges after the open. This is a known DRC risk and should
be **validated with DRC per style** (§8).

**Recommended robust approach for diagonal screens: render them as TRUE rotated-rectangle
polygons in KLayout, not pixel staircases.** Instead of setting pixels, generate, for a
diagonal-screened region:

1. Compute the set of parallel stripes at 45°/135° covering the region's bounding box:
   each stripe is a **rotated rectangle** of width `w·pixel_size` on the metal grid,
   spaced by `P·pixel_size`, at the exact angle.
2. Build them as `db.DPolygon` rotated rectangles (or axis-aligned rectangles transformed
   by `db.DCplxTrans` with the rotation angle), and **intersect** (`db.Region &`) with the
   region's coverage mask.
3. Insert the resulting clean-edged polygons directly.

This yields exact-width diagonal metal with straight (if off-Manhattan) edges rather than
staircases. **Note:** GF180 tolerates 45° geometry, but *arbitrary* angles risk acute-angle
rules — keep diagonals to exactly 45°/135°. Flag this whole area as **validate-with-DRC**;
if true-polygon 45° still flags acute-angle rules, fall back to Manhattan staircase +
declobber (which is proven clean on the prototype's orthogonal styles).

Orthogonal styles (`hline`, `vline`, `mesh`) are always pixel-perfect on the Manhattan grid
and need no special handling.

### 4.7 Emit GDS

For each metal pixel, emit a `pixel_size × pixel_size` µm square (a `db.DBox`) at
`(x·pixel_size, (H − y − 1)·pixel_size)` — note the **y-flip** (image origin is top-left,
GDS origin is bottom-left). Insert on **each** requested foreground metal layer. Then:

- **`--merge`** (strongly recommended): insert all squares into a `db.Region`, `merge()`
  them into consolidated polygons (fewer shapes, cleaner edges, DRC-friendlier), and insert
  the merged region on each foreground layer. Optionally `smooth()` at ~`pixel_size·0.99`.
- Draw the **boundary / PR box** as a `db.DBox` from `(0,0)` to `(W·pixel_size,
  H·pixel_size)` on the boundary layer(s).
- Layout `dbu = 0.001` (1 nm). Write with `ly.write(output.gds)`.

**GDS layer map (GF180MCU, locked v1):**

| Purpose | Layer/Datatype |
|---|---|
| Metal1 | `34/0` |
| Metal2 | `36/0` |
| Metal3 | `42/0` |
| Metal4 | `46/0` |
| Metal5 | `81/0` |
| Boundary / PR-box | `152/5` |

Using **all five** metal layers stacks the art through the full metal stack (reads boldly
in a die photo). Fewer layers = subtler / lower local density. `pixel_size` sets physical
size: **final µm = grid_px × pixel_size**; default recipe `pixel_size = 0.60` → 800 px art
= **480 × 480 µm** (matches the prototype macro's `SIZE 480 BY 480`).

### 4.8 Wide-metal guard: max solid short-dimension (MSLOT)

*The hard silicon limit that turns "art" into "DRC-clean art." Derived + DRC-verified on
the eurosynth art macros (gf180mcuD, `beol=true`), 2026-07-03.*

**A filled metal region may be long, but its *short* dimension (width) must stay under
~30 µm.** Any region that is ≥ ~30 µm in **both** directions is "wide metal" and the PDK
requires it to be slotted; an unslotted wide blob fails DRC (`MSLOT.*`, one hit per metal
layer M1–M5).

- Long + thin is fine: a strip 5 µm tall × 400 µm long passes (short dim 5 µm).
- Square-ish + big fails: a ~30 × 30 µm solid pad fails (both dims ≥ 30 µm).
- Verified: a solid blob was clean at 480 µm macro scale, tripped MSLOT at 520 µm.
- Verified: line-screened strips up to ~11 µm tall of *any* length are clean.

**Renderer rule (enforce at synthesis time):**

> Never emit a connected solid-metal component whose **minimum width exceeds ~28 µm**
> (keep a margin under the 30 µm rule). If a region would be larger than that in both
> axes, break it up — screen it (lines/dots/mesh) so every resulting metal strip is thin
> in at least one axis.

This is a *geometry* rule, so it must be applied **after** the screen is synthesised
on-grid, on the actual metal bitmap/polygons — **not** on the source image.

**Translating to pixels.** The renderer works in pixels at `pixel_size` µm/px. Convert
the limit once:

```
max_solid_short_px = floor(30 / pixel_size) - safety_margin
# pixel_size = 0.60 µm  ->  30/0.60 = 50 px  ->  cap solid strips at ~46 px short-dim
```

So at 0.60 µm/px, keep any solid feature under ~46 px in its narrow dimension. A cheap,
conservative detector for "≥ limit in both axes": slide an `S × S` all-metal window
(`S = max_solid_short_px`) over the post-cleanup bitmap via a summed-area table — any hit
marks a region that needs breaking up. (The browser preview, §5.3, runs exactly this
check live and outlines offending regions.)

**v1.2 default: solid is never literal.** "Solid"-classified regions render as
**auto-slotted solid** — full fill minus a 2×2 slot hole per `dot_pitch` cell (§4.4),
i.e. the darkest grey tone (≈ 96% fill at the default 10 px cell, holes every 6 µm),
and the grey tone curve is capped at the same pattern. Black regions are therefore
self-slotting *by construction* and the guard above becomes a verification net rather
than an active fixer. The only remaining way to produce a wide solid blob is the
`solid_fill: true` config escape hatch — the detector still catches it.

> **Verification note:** the slot geometry is legal (a 2×2 px hole = 1.2 µm ≥ min
> space), but whether *isolated small holes* satisfy the deck's MSLOT slot
> requirements is **not yet silicon-DRC-verified** — the empirically verified-clean
> patterns are continuous gap *lines* every ≤ ~12 µm (`solid_screen`, below). Re-run
> the §8 DRC on the first GDS generated with auto-slotted solids; if MSLOT still
> flags, enlarge the hole (3×3 or 2×4 per cell) or fall back to `solid_screen` lines.

**The `solid_screen` knob — the prototype's line-fill alternative.** `solid_screen = P`
fills a "solid"-classified region with horizontal lines of `feature = P − 2` px,
`gap = 2` px. Every emitted strip is `feature` px tall (short dim) and arbitrarily long:

- Clean for **any** pitch as long as `feature < max_solid_short_px` (≈ 46 px @ 0.60 µm).
- Density = `(P − 2)/P`, so higher pitch = darker. `P = 20` ≈ 90% fill (18 px = 10.8 µm
  strips), comfortably clean and near-black in a die photo.
- **Upper-bound caveat:** if `P` gets so large that a whole letter-body/stroke is thinner
  than one pitch, it receives *no* gap and reverts to a fully solid 2-D blob — which can
  then exceed 30 µm in both axes and re-trip MSLOT. Cap the pitch so a gap falls inside
  every fillable region (`P ≈ 20` was the safe max for the blackletter logo).

**The other floor — min feature/gap — is unchanged:** the binding constraint is not the
PDK width/space minimums but the cleanup pass; every feature *and* gap must be **≥ 2 px**
to survive the 2×2 open (§2.3, §4.4). At 0.60 µm/px, 2 px = 1.2 µm, already well above
the 0.23/0.28 µm floors.

**What the renderer does NOT need to handle.** These are **die-level** rules that any
isolated metal-only macro trips and that clear at chip integration (dummy fill / full
floorplan) — not the renderer's job, don't chase them:

- `M1.4 M2.4 M3.4 M4.4 M5.4` — per-layer minimum metal density
- `MT.3` — top-metal density
- `PL.8` — a passivation/dummy rule

A clean isolated art macro therefore floors at **7 "benign" violations, zero of them
width/space/area/MSLOT**. That "7 and only 7" is the renderer's pass/fail target (§8.3).

---

## 5. Components & architecture

Three components share one **style registry / config** so preview and output never diverge.

```
                    ┌───────────────────────────────┐
                    │  config (YAML/JSON)            │
                    │  pixel_size, pitch, layers,    │
                    │  thresholds, style_registry    │
                    └───────────────┬───────────────┘
             ┌──────────────────────┼──────────────────────┐
             ▼                      ▼                      ▼
     ┌──────────────┐      ┌──────────────┐      ┌──────────────────┐
     │ Core library │      │     CLI      │      │  Browser preview │
     │ (Python)     │◄─────│  make art    │      │  (HTML/Canvas/JS)│
     │ img→GDS +    │      │  wraps core  │      │  mirrors screens │
     │ control sys  │      └──────────────┘      │  live coverage % │
     └──────────────┘                            └──────────────────┘
```

### 5.1 Core library (Python)

The engine. A package (proposed `mhs/`) exposing:

- `classify(h, s, v) -> (style, density)` — the §3 mapping.
- `feat(density, pitch) -> width` — `_feat`.
- Style generators — a **registry** `STYLES: {name: fn(x, y, pitch, width) -> bool}`
  implementing §4.4. This registry is exported (as JSON) for the preview to consume.
- `open2(img)`, `declobber(img)` — §4.5 cleanup.
- `synthesize(control_rgba, cfg) -> stencil_1bit` — the §4.1–§4.5 pipeline (ingest+alpha,
  resize, classify, screen, open, declobber).
- `to_gds(stencil, cfg, out_path)` — §4.7 emission (merge, layers, boundary, y-flip).
- `coverage(stencil) -> float` — fraction of metal pixels (for reporting & the preview's
  live number).

Dependencies: **Pillow (PIL)** for raster ops, **`klayout` pip package** (`klayout.db`,
headless) for GDS. The core must run in the `python:3.12-slim` container (§8) with no
native EDA.

The library must be **pure and deterministic**: same control image + same config → byte
-identical GDS. No wall-clock, no randomness (the "clustered dot" is deterministic).

### 5.2 CLI (`make art`)

A thin wrapper over the core, driven by a config file plus overrides. Suggested interface
(argparse or click):

```bash
# Generate art GDS + the four macro views from a control image and a config:
mhs art  --control control.png  --config recipe.yaml  --out build/

# Override individual knobs (config values are defaults):
mhs art  --control control.png \
         --pixel-size 0.60  --pitch 5  --size 480x480 \
         --layers M1,M2,M3,M4,M5 \
         --cellname eurosynth_art  --out build/

# Just DRC an existing art GDS (delegates to the Docker/KLayout step, §8):
mhs drc  --gds build/eurosynth_art.gds  --report build/report.lyrdb

# Emit macro views (lef/lib/vh) for an already-generated GDS:
mhs macro  --gds build/eurosynth_art.gds  --size 480x480  --cellname eurosynth_art
```

Parameters (all also settable in the config file, §7):

| Param | Meaning | Default |
|---|---|---|
| `--control` | control-image PNG (RGBA) | (required) |
| `--pixel-size` | µm per grid pixel | 0.60 |
| `--pitch` (`--screen`) | screen pitch in px | 5 (≈3 µm) |
| `--size` | target physical size `WxH` µm (→ grid via pixel_size) | 480x480 |
| `--layers` | metal layers to draw on | M1..M5 |
| `--cellname` | GDS top cell + macro name | `art` |
| `--merge` | fuse pixels into polygons | on |
| `--out` | output directory | `build/` |
| `--config` | YAML/JSON recipe (see §7) | none |

The CLI is the authoritative generator; the Makefile-style recipe from the prototype
(`make art SCREEN=8 …`) maps onto these flags.

### 5.3 Live browser preview tool

A **single self-contained HTML file** (HTML + inline CSS + inline JS + `<canvas>`, no build
step, no server) that lets the artist load or lightly paint a control image and **see the
exact on-grid 1-bit metal result in real time**, with a **live metal-coverage %** readout.
It must draw the **same on-grid screens** the core library emits so preview == output.

**Why it exists:** the Docker→DRC round-trip is slow (minutes). The preview closes the
iteration loop to milliseconds for the *look* and *coverage*, so the user only invokes the
heavy path once they're happy.

**Layout / UI:**

```
┌───────────────────────────────────────────────────────────────┐
│  Metal Halftone Studio — Preview                               │
├──────────────┬────────────────────────────────────────────────┤
│  CONTROLS     │   CANVAS AREA                                  │
│              │   ┌───────────────┬───────────────┐            │
│  Load PNG…   │   │ Control (color)│ Output (1-bit)│            │
│  Paint tools │   │   as painted   │  on-grid metal │            │
│   [swatches] │   └───────────────┴───────────────┘            │
│              │                                                 │
│  pixel_size  │   Metal coverage:  37.4 %   [target > 30%]      │
│   [slider]   │   Grid: 800 × 800 px  =  480 × 480 µm           │
│  pitch       │   Est. shapes: 12,481                           │
│   [slider]   │                                                 │
│  tone thresh │   ┌─ zoom [1:1] [fit] ──────────────┐          │
│   solid V    │   │  (pixel-accurate zoom of a       │          │
│   empty V    │   │   selected patch to inspect      │          │
│   sat floor  │   │   min-width survival)            │          │
│              │   └──────────────────────────────────┘          │
│  Export ▾    │                                                 │
│   • control PNG                                                │
│   • GDS (stretch)                                              │
└──────────────┴────────────────────────────────────────────────┘
```

**Panels:**

- **Control view** — the color control image the user loaded/painted (source of truth).
- **Output view** — the synthesised 1-bit metal stencil, black = metal on a light-silicon
  background (or invert to taste), rendered at the current `pixel_size`/`pitch`.

**Canvas rendering approach (must match the core):** the JS re-implements the *same*
pipeline as the core library:

1. Draw/resize the control image onto an offscreen canvas at the **target grid resolution**
   (`grid_px = size_µm / pixel_size`) — the on-grid rule (§2.2) applies in the browser too.
2. `getImageData`, convert each pixel RGB→HSV, run the **same `classify`** (§3.1).
3. Run the **same style generators** (§4.4) using the **shared style registry** exported
   from the core as JSON (do **not** hand-copy the formulas — import the one table so they
   can't drift).
4. Run a JS port of **`open2` + `declobber`** (§4.5) so the previewed coverage/edges match
   the DRC-clean output, not the raw screen.
5. Paint the resulting 1-bit buffer to the output canvas; **count metal pixels → coverage
   %** and update the readout live.

A **1:1 pixel-zoom inspector** lets the user zoom to individual grid pixels to eyeball that
features/gaps are ≥2 px (a proxy for min-width survival) before committing.

**Controls:**

| Control | Effect |
|---|---|
| Load PNG | load a control image (must be/forced to RGBA — warn if no alpha, §4.1) |
| Paint swatches | light painting with the six legend colors + black/white/grey ramp, for tweaks |
| `pixel_size` slider | µm/px → changes grid resolution & physical size; re-synthesise |
| `pitch` slider | screen pitch (px); re-synthesise |
| tone thresholds | `solid V`, `empty V`, `sat floor` — the §3.1 cut points (live) |
| zoom | 1:1 / fit for the inspector |
| Export ▾ | **control PNG** (feed to the CLI) or **GDS** (stretch goal, §9 phase 4) |

**Live metal-coverage %:** displayed prominently with the die-level context ("die must be
> 30%, satisfied by fill at integration — this macro's local coverage is X%"). Coverage is
`metal_pixels / total_pixels` on the post-cleanup buffer. Also show grid dimensions, physical
size, and an estimated shape count.

**Export:** primary export is the **control PNG** (canonical input to the CLI — the browser
is a *previewer*, the CLI is the authoritative generator). Stretch goal: emit the GDS
directly from the browser (§9 phase 4) — feasible via a WASM build of KLayout or a
hand-rolled GDSII writer in JS, but not required for v1.

---

## 6. Macro packaging (the four macro views)

To place the art in a chip, the studio emits a self-contained **art macro** with four views
(mirroring `ip/eurosynth_art/{gds,lef,lib,vh}/`). The macro is an **inert obstruction black
box**: no logic, no pins, no nets.

### 6.1 The four views

| View | File | Contents | Purpose |
|---|---|---|---|
| **GDS** | `gds/<cell>.gds` | the metal-art polygons on M1–M5 + boundary `152/5` (§4.7) | the physical art |
| **LEF** | `lef/<cell>.lef` | a `MACRO … CLASS BLOCK` of the art's exact `SIZE`, with **OBS (obstruction) rectangles on Metal1–5 covering the whole footprint** | tells the router/PDN to treat the art as a keep-out and route *around* it (no shorts to power straps) |
| **LIB** | `lib/<cell>.lib` | a **trivial empty Liberty cell** (just threshold defs + an empty `cell(<name>){}`) | satisfies the flow's requirement for a `.lib` per corner without adding timing |
| **VH** | `vh/<cell>.v` | a **blackbox Verilog stub**: `(* blackbox *) module <name>; endmodule` | lets synthesis/LVS see the instance as an intentional empty black box |

**LEF template** (obstruct all five metals over the full footprint):

```lef
VERSION 5.7 ;
  NOWIREEXTENSIONATPIN ON ;
  DIVIDERCHAR "/" ;
  BUSBITCHARS "[]" ;
MACRO <cell>
  CLASS BLOCK ;
  FOREIGN <cell> ;
  ORIGIN 0.000 0.000 ;
  SIZE <W_um> BY <H_um> ;
  OBS
      LAYER Metal1 ; RECT 0.0 0.0 <W_um> <H_um> ;
      LAYER Metal2 ; RECT 0.0 0.0 <W_um> <H_um> ;
      LAYER Metal3 ; RECT 0.0 0.0 <W_um> <H_um> ;
      LAYER Metal4 ; RECT 0.0 0.0 <W_um> <H_um> ;
      LAYER Metal5 ; RECT 0.0 0.0 <W_um> <H_um> ;
  END
END <cell>
END LIBRARY
```

**LIB template** (empty cell; 9 process corners reuse the same file):

```liberty
library (<cell>) {
  input_threshold_pct_fall: 50.0;   input_threshold_pct_rise: 50.0;
  output_threshold_pct_fall: 50.0;  output_threshold_pct_rise: 50.0;
  slew_lower_threshold_pct_fall: 20.0;  slew_lower_threshold_pct_rise: 20.0;
  slew_upper_threshold_pct_fall: 80.0;  slew_upper_threshold_pct_rise: 80.0;
  cell (<cell>) { }
}
```

**VH template:**

```verilog
(* blackbox *)
module <cell>;
endmodule
```

The `mhs macro` subcommand generates all four from the config (it knows `<cell>`, size in
µm, and layer set).

### 6.2 Dropping it into a LibreLane / wafer.space chip flow

Per the host repo's mechanism (`docs/chip_art.md`), integration is:

1. **Register the macro** in the flow's macros YAML (e.g. `librelane/macros/macros_5v.yaml`
   *and* `macros_3v3.yaml` — one dict each, because the flow does **no deep-merge**):

   ```yaml
   <cell>:
     gds:  [dir::../ip/<cell>/gds/<cell>.gds]
     lef:  [dir::../ip/<cell>/lef/<cell>.lef]
     vh:   [dir::../ip/<cell>/vh/<cell>.v]
     lib:  { "*": [dir::../ip/<cell>/lib/<cell>.lib] }   # same empty lib all corners
     instances:
       art_inst: { location: [X, Y], orientation: N }    # inside the core, clear of sealring/marker
   ```

2. **Ignore the disconnected module** — the art has no nets, so add `<cell>` to
   `IGNORE_DISCONNECTED_MODULES` in the flow config (or LVS/synthesis flags it).

3. **Instantiate the black box** in the top RTL as a kept, empty instance
   (`(* keep *) <cell> art_inst ();`) so it survives synthesis.

4. **Re-harden + re-signoff** the chip (full run) and re-run the CoB/precheck, since the
   GDS changed. The art is physically inert (obstruction only), so it should stay green;
   the one thing to watch is **local metal density** on a large *solid* graphic — mitigate
   via outline-style art, fewer metal layers, or smaller size (screened art is inherently
   low-density and safe).

The die-level **>30% coverage** rule is handled by **dummy fill** at chip integration, not
by this macro.

---

## 7. File formats & conventions

### 7.1 Input: control image

| Property | Requirement |
|---|---|
| Format | **PNG** (v1). JPEG tolerated but discouraged (compression fuzzes hue/edges). |
| Mode | **RGBA** — a **real alpha channel is required** (§4.1). Opaque RGBA (alpha=255) is correct. Studio forces `.convert("RGBA")` and warns if the source lacked alpha. |
| Size | Any; it is resized to the target grid (`size_µm / pixel_size`) before screening. Author it **large** (e.g. ≥1000 px) so the resize is a downscale, preserving crisp edges. |
| Color meaning | Per the §3 locked legend (black=solid, white=empty, grey=H-line by darkness, the six hues → styles, saturation/lightness → density). |
| Background | White = bare silicon. Paint only what you want as metal/screen. |

### 7.2 Output: GDS + macro views

- `build/<cell>.gds` — the art (M1–M5 polygons + `152/5` boundary), `dbu = 0.001`.
- `build/<cell>.lef`, `build/<cell>.lib`, `build/<cell>.v` — the three companion views
  (§6.1).
- `build/report.lyrdb` — KLayout DRC report (§8).
- `build/preview.png` — a rasterized preview of the 1-bit stencil (for eyeballing).

### 7.3 Config file (YAML or JSON)

Captures the full recipe so a build is reproducible. Example (`recipe.yaml`):

```yaml
cellname:   eurosynth_art
control:    control.png
pixel_size: 0.60          # µm per grid pixel
size_um:    [480, 480]    # target physical size; grid = size_um / pixel_size
pitch:      5             # screen pitch in px  (~3 µm at 0.60)
dot_pitch:  10            # grey halftone cell in px (default 2x pitch) — larger =
                          # sparser light greys, more tone levels (§4.4)
solid_fill: slotted       # v1.2: "solid" = full fill minus a 2x2 slot hole per
                          # dot_pitch cell (the darkest grey tone, §4.4/§4.8).
                          # hline:<P> = the prototype's solid_screen line fill;
                          # true = literal solid (requires the §4.8 guard)
merge:      true
layers:                   # GDS metal layers to draw on
  Metal1: "34/0"
  Metal2: "36/0"
  Metal3: "42/0"
  Metal4: "46/0"
  Metal5: "81/0"
boundary:   "152/5"

thresholds:               # §3.1 HSV cut points (0..1)
  solid_v:    0.28
  solid_s:    0.35
  empty_v:    0.90
  empty_s:    0.12
  grey_s_max: 0.12
  # grey density floor is DERIVED, not configured: 4.5 / dot_pitch²  (§4.4)

grey_tone:                # global tone curve for grey halftone (§4.4); identity defaults
  gamma:      1.0         # 0.3..3, applied first — bends mid-tones
  contrast:   1.0         # 0.25..3 — slope about mid-grey
  brightness: 0.0         # -0.5..0.5 — shifts the range; can drop lights to empty
  color_s_floor: 0.12
  color_density_div: 0.55
  color_density_floor: 0.20

# Single source of truth shared with the browser preview (§3.4, §5).
# Grey (S < grey_s_max) maps to clustered dots; hue bands only apply to color.
style_registry:           # hue band (deg) -> style name
  - { hue: [340, 20],  style: xmesh }   # red (wraps)
  - { hue: [20, 45],   style: brick }   # orange
  - { hue: [45, 75],   style: d45   }   # yellow
  - { hue: [75, 150],  style: mesh  }   # green
  - { hue: [150, 200], style: d135  }   # cyan
  - { hue: [200, 250], style: hline }   # blue
  - { hue: [250, 290], style: weave }   # violet
  - { hue: [290, 340], style: vline }   # magenta

drc:
  deck: "$PDK_ROOT/$PDK/libs.tech/klayout/tech/drc/gf180mcu.drc"
  feol: false
  beol: true
```

Conventions: physical size is always derived (`grid = round(size_um / pixel_size)`); the
`style_registry` and `thresholds` are exported to the browser as JSON so preview and CLI
share one definition.

---

## 8. Build & DRC workflow

No native EDA on the dev machine — everything runs in throwaway Docker containers.

### 8.1 Generate the GDS (python:3.12-slim container)

```bash
docker run --rm -v "$PWD":/work -w /work python:3.12-slim bash -c '
  apt-get update -qq &&
  apt-get install -y -qq libexpat1 libglib2.0-0 &&      # klayout runtime deps
  pip install -q klayout pillow &&
  python -m mhs art --control control.png --config recipe.yaml --out build/
'
```

`klayout` (the pip package) provides headless `klayout.db`; `libexpat1` + `libglib2.0-0`
are its shared-lib deps. Pillow does the raster ops.

### 8.2 Metal DRC (KLayout against the GF180MCU deck)

Run the PDK's KLayout DRC deck on the generated GDS, metal-only (`feol=false beol=true` —
the art has no transistors):

```bash
klayout -b -zz \
  -r "$PDK_ROOT/$PDK/libs.tech/klayout/tech/drc/gf180mcu.drc" \
  -rd input=build/<cell>.gds \
  -rd report=build/report.lyrdb \
  -rd feol=false -rd beol=true
```

(Run inside a container that has `klayout` + the GF180MCU PDK mounted, matching the host
repo's `make drc` target.)

### 8.3 What "clean" means

- **Zero violations** on width, space, area, notch, and MSLOT for the art itself. This is
  the bar; the pipeline (on-grid synthesis + `_feat` ≥2 px + open + declobber + the §4.8
  wide-metal guard) is designed to hit it.
- The **only expected/benign flags** are **die-level density rules** that any isolated
  metal-only macro trips and that dummy fill / the full floorplan satisfies at chip
  integration: `M1.4`–`M5.4` (per-layer metal density), `MT.3` (top-metal density), and
  `PL.8` (passivation/dummy). A clean isolated art macro floors at exactly these
  **7 benign violations — "7 and only 7"** is the pass/fail target (verified on the
  eurosynth art macros, gf180mcuD, 2026-07-03). Everything else must be zero.
- If a **diagonal style** (§4.6) produces min-width / notch / acute-angle hits, that is the
  known staircase risk: switch that style to the **true rotated-polygon** renderer, or fall
  back to an orthogonal style. Always re-DRC after changing a diagonal style.

Interpretation: open `report.lyrdb` in KLayout (or parse it) — group by rule, confirm the
only non-empty categories are the 7 benign die-level ones (`M1.4`–`M5.4`, `MT.3`, `PL.8`),
and that all width/space/area/MSLOT categories are empty.

---

## 9. Repo structure, dependencies & roadmap

### 9.1 Proposed repo tree

```
metal-halftone-studio/
├── SPEC.md                     # this document
├── README.md                   # quickstart
├── pyproject.toml              # package + deps (pillow, klayout)
├── mhs/                        # core library (Python)
│   ├── __init__.py
│   ├── classify.py             # HSV → (style, density)   §3
│   ├── styles.py               # STYLES registry, _feat   §4.4
│   ├── cleanup.py              # open2, declobber          §4.5
│   ├── synth.py                # synthesize(): full raster pipeline §4.1–4.5
│   ├── gds.py                  # to_gds(): klayout emission §4.7
│   ├── macro.py                # lef/lib/vh emitters        §6.1
│   ├── config.py               # load/validate recipe, export JSON for preview §7.3
│   └── cli.py                  # `mhs art|drc|macro`        §5.2
├── preview/
│   └── index.html              # self-contained live preview §5.3
├── registry.json               # exported style_registry+thresholds (shared w/ preview)
├── recipes/
│   └── default.yaml            # the default recipe (pixel_size 0.60, pitch 5, M1–5)
├── examples/
│   ├── control_logo.png        # sample RGBA control map
│   └── legend.png              # the color legend as an image
├── scripts/
│   ├── generate.sh             # §8.1 Docker generate
│   └── drc.sh                  # §8.2 Docker DRC
├── build/                      # (gitignored) gds/lef/lib/vh/report/preview outputs
└── tests/
    ├── test_classify.py        # HSV boundary cases
    ├── test_feat.py            # width/gap ≥2 invariants
    ├── test_cleanup.py         # open/declobber remove pinches
    └── test_golden_gds.py      # determinism: same input → same GDS
```

### 9.2 Dependencies

| Dependency | Where | Why |
|---|---|---|
| Python 3.12 | core, CLI | language |
| Pillow (PIL) | core | raster ops (open, resize, HSV, ImageChops for morphology) |
| `klayout` (pip) | core | headless `klayout.db` GDSII writer |
| Docker | build/DRC | reproducible env with no native EDA (`python:3.12-slim`) |
| KLayout + GF180MCU PDK deck | DRC | metal DRC signoff (`gf180mcu.drc`, `beol=true`) |
| (browser only) | preview | pure HTML/Canvas/JS — **no** external deps, no build step |

### 9.3 Phased roadmap

| Phase | Deliverable | Scope |
|---|---|---|
| **1 — MVP (CLI)** | `mhs art` produces a DRC-clean GDS + the four macro views from a control PNG. | Core library (§4 pipeline, orthogonal styles pixel-perfect; diagonals as staircase + declobber), CLI, config, Docker generate + DRC scripts, golden-GDS test. Prove **zero** width/space/area/MSLOT violations on a real control image. |
| **2 — Live preview** | `preview/index.html` renders the same on-grid 1-bit result + live coverage %, exports the control PNG. | JS port of classify/styles/open/declobber driven by the **shared `registry.json`**; pixel-zoom inspector; sliders for pixel_size/pitch/thresholds. Verify preview coverage matches the CLI's `coverage()` on the same input. |
| **3 — True-polygon diagonals** | `d45`/`d135`/`xmesh` (yellow/cyan/red) rendered as true rotated-rectangle polygons in KLayout (§4.6). | Add polygon-stripe generator; DRC-validate 45°/135° against acute-angle rules; keep Manhattan fallback. |
| **4 — GDS export from browser (stretch)** | Preview can emit the GDS directly (WASM KLayout or a JS GDSII writer). | Optional; the CLI remains the authoritative generator. |

**Definition of done for v1:** phases 1–2 complete; a sample control image round-trips to a
GDS that passes GF180MCU metal DRC with only the benign die-density floor outstanding; the
browser preview's on-grid result and coverage % match the generated output.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| **1-bit / binary metal** | Metal is present or absent at each point; no grayscale. All tone is pattern. |
| **Halftone screen ("screen")** | A regular pattern (lines/mesh/dots) whose metal-coverage fraction encodes tone. |
| **Pitch (`screen`, `P`)** | The repeat period of the screen, in grid pixels. Feature + gap fit within one pitch. Recommend ≥ ~3 µm. |
| **Feature width (`w`, `_feat`)** | Width (px) of the metal part of one screen period; both `w` and the gap stay ≥ 2 px. |
| **Density** | Target tone 0..1; maps to `w` via `_feat`. Comes from grey darkness or color saturation. |
| **On-grid synthesis** | Building the screen *at* the metal grid resolution (after resizing the source), so every feature/gap lands on-grid at a legal width — as opposed to downscaling a pre-dithered image (which shatters into slivers). |
| **Control map / control image** | The colored input image; each region's color picks its screen style, its saturation/lightness picks density. |
| **`_open2` (2×2 open)** | Morphological opening (erode then dilate) that removes sub-2px slivers/spurs from the screen. |
| **`_declobber`** | Pass that breaks diagonal 2×2 corner-touches: a metal-metal diagonal (zero-width pinch) and its complementary empty-empty diagonal (zero-space pinch); filling one corner clears both. |
| **MSLOT.1** | GF180 rule: solid metal wider than 30 µm needs stress-relief slots (holes). Screened art self-slots; large solid fills can trip it. |
| **Min width / min space / min area** | GF180 metal minimums: 0.23 µm (M1) / 0.28 µm (M2–5) width & space; 0.1444 µm² area. |
| **Die coverage (>30%)** | Die-wide metal-density floor; benign here, satisfied by dummy fill at chip integration, not by the art macro. |
| **Art macro** | The self-contained GDS + LEF + LIB + VH bundle that drops the art into a chip flow as an inert obstruction black box. |
| **Obstruction (OBS)** | LEF geometry marking the macro footprint as a router/PDN keep-out so nothing routes over/into the art. |
| **Black box** | A module with a declared interface (here: none) but no internals; kept through synthesis, ignored by LVS via `IGNORE_DISCONNECTED_MODULES`. |
| **`pixel_size`** | µm per grid pixel; final size µm = grid_px × pixel_size. Default 0.60 → 800 px = 480 µm. |
| **BEOL / FEOL** | Back-/front-end-of-line. Art is metal-only → DRC runs BEOL (`beol=true feol=false`). |
| **dbu** | GDS database unit; here 0.001 µm (1 nm). |
| **wafer.space slot** | A fabrication slot (e.g. "1×0p5") on a shared GF180MCU shuttle that the art targets. |

---

*End of spec. The v1.2 mapping in §3 is locked; extensions per §3.4 are additive and must
not change v1.2 behavior.*
