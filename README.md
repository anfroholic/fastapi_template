# Open Silicon Component Exchange (prototype)

A **"Thingiverse for chips"** — a catalog where designers browse and download
pre-hardened silicon macros (an oscillator, a UART, an SRAM, a filter) and drop
them straight into their own chip flow without re-running hours of place-and-route.

This is a **display / UX prototype**: it focuses on how a component is presented
and browsed. Users, auth, and publishing are intentionally out of scope for now.

Built on the FastAPI + Jinja2 template — no database, no frontend build step.

The catalog is seeded with **real hardened macros imported from [EuroSynth](https://github.com/anfroholic/eurosynth)** —
five GF180MCU audio-synth engines (Karplus–Strong, neural oscillator, chaos, SID,
bytebeat), the wafer.space shuttle-ID blocks, and a **metal-halftone die-art
macro** — each with genuine GDS / LEF / Verilog / Liberty views.

## What's here

- **Catalog** (`/`) — a playful grid of component cards with faceted filtering
  (function, PDK, node, license), search, sorting, and a "fully signed-off only"
  toggle. Each card shows the **rendered layout** (GDS view) and, for the audio
  engines, a **▶ play button** that previews the chip's actual sound.
- **Detail** (`/component/<name>`) — a datasheet-style page with:
  - the **layout render** — the GDS rasterized with GF180MCU layer colors (the
    same KLayout render the chip flow emits at signoff),
  - the LEF-parsed **footprint** (outline + labeled, bus-grouped pins; power pins
    separated),
  - an inline **audio preview** for the engines,
  - **signoff traffic lights** (DRC / LVS / setup / hold),
  - a **corner-coverage matrix** (process × operating point, N of 9),
  - a **Files** panel listing every file in the package (grouped by view, with
    sizes), and an **in-browser viewer** — click *view* to read any text file
    (`component.yaml`, `.lef`, `.vh`, `.lib`) with syntax highlighting and line
    numbers in a modal; binaries download,
  - a copy-paste `MACROS:` integration snippet, specs, and a provenance link.
- **Downloads** — whole-package `.zip` on the fly, or any single view file.
- **Studio** (`/studio`) — the *create* side: a live **Metal Halftone Studio**
  preview. Paint a color control map (color → screen style, saturation → density)
  and watch it synthesize the exact on-grid, 1-bit metal stencil a die-art macro
  is built from — same pipeline the generator runs (resize-to-grid first, HSV
  classify, on-grid screens, 2×2 open, declobber), with live metal-coverage %, a
  **live wide-metal (MSLOT) check** that outlines any solid region big enough to
  need stress-relief slots, a pixel inspector, a full-screen zoom/pan preview, a
  **per-color remap panel**
  (every color in the map broken out — override its screen style or fill density
  when the automatic mapping isn't the weight you pictured), aspect-ratio-true
  image import, and control-PNG export. The full spec lives in
  [`art.md`](art.md); the [`eurosynth_art`](app/components/eurosynth_art) macro
  in the catalog is a real output of that pipeline.

## The "GDS view" — how it's rendered, and what it costs

A GDS is opaque binary mask geometry, but it's exactly what you eyeball after
hardening a chip. [`app/render_gds.py`](app/render_gds.py) rasterizes each macro's
GDS to a PNG using the pip `klayout` module's headless `LayoutView` and GF180MCU's
own layer-style file (`app/gf180mcu_render.lyp`) — the *same* `KLayout.Render` step
the LibreLane flow runs at signoff.

The key point on cost: this **reads the already-hardened GDS**, so it's just
rasterization, not place-and-route. All ten macros render in **~4 s total** on a
laptop CPU — no GPU, no PDK tools. That's the difference between *viewing* a layout
(seconds) and *producing* one (the original hardening: minutes-to-hours of CPU per
block).

The GDS files are committed **gzip'd** (`gds/<name>.gds.gz`, ~7.7 MB total vs 54 MB
raw — 7×). KLayout and most EDA tools read `.gds.gz` directly, so nothing needs the
raw file.

```
python render_gds.py            # renders all -> components/<name>/render/<name>.png
```

The app shows a render wherever one exists and falls back to the LEF footprint SVG
otherwise, so the render step is optional at runtime.

## How a component is stored

Each package under `app/components/<name>/` follows the spec's 4-view layout:

```
<name>/
  gds/<name>.gds.gz                    # layout (real GDSII, gzip'd)
  lef/<name>.lef                       # abstract: outline + pins  <- parsed for the footprint
  vh/<name>.vh                         # black-box Verilog interface
  lib/<corner>/<name>__<corner>.lib    # timing, one dir per PVT corner
  render/<name>.png                    # rasterized layout (produced by render_gds.py)
  component.yaml                       # catalog metadata
```

### Populating the catalog

- **Real macros** — [`app/import_eurosynth.py`](app/import_eurosynth.py) copies the
  four views out of a local EuroSynth checkout and synthesizes each `component.yaml`
  (size + corners read from the real LEF/lib; the rest curated per macro):
  `python import_eurosynth.py [path-to-eurosynth]` (defaults to `../../eurosynth`).
  Then `python render_gds.py` to produce the layout images.
- **Synthetic macros** — [`app/seed_components.py`](app/seed_components.py) generates
  fabricated packages for UI work without a real PDK checkout; edit `COMPONENTS` and
  re-run. (The importer overwrites `app/components/`, so run one or the other.)

## Code map

| File | Role |
|------|------|
| `app/main.py` | FastAPI routes: catalog, detail, render.png, downloads |
| `app/catalog.py` | Loads packages, computes derived fields (corner matrix, freq, audio, render) |
| `app/lef.py` | LEF parser (bus-grouping, power-pin split) + SVG footprint renderer |
| `app/render_gds.py` | Rasterizes each GDS to a PNG via headless KLayout (the "GDS view") |
| `app/import_eurosynth.py` | Imports real hardened macros from the EuroSynth repo |
| `app/seed_components.py` | Generates synthetic sample packages |
| `app/htmldirectory/*.html` | Jinja templates (`base`, `catalog`, `detail`, `studio`, `_widgets`) |
| `app/static/studio.js` | Halftone Studio: the in-browser control-map → stencil pipeline |
| `app/static/style.css` | Theme |
| `art.md` | Metal Halftone Studio spec (the generator the studio previews) |

## Run it

From the root of this directory:

```
docker-compose up --build
```

then open http://localhost:8080 (OpenAPI docs at http://localhost:8080/docs).

Subsequent runs: `docker-compose up`. Stop: `docker-compose down`.
The `--reload` flag reloads on any `.py` save.
