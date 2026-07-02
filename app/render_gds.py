"""Render each macro's GDS to a PNG — the catalog's "GDS view".

A GDS is opaque binary mask geometry, but it is exactly what a foundry ships and
what you eyeball after hardening a chip. KLayout can rasterize it with proper
per-layer colors; this is the same rendering the LibreLane chip flow emits at
signoff (its ``KLayout.Render`` step). We reuse GF180MCU's layer-style file
(``gf180mcu_render.lyp``) so the colors match the real flow.

Runs fully headless via the pip ``klayout`` module's offscreen LayoutView — no
GUI, no full re-hardening. It reads the *already-hardened* GDS, so the cost is
just rasterization (seconds), not place-and-route (hours).

Usage:
    python render_gds.py [macro_name ...]      # default: all with a GDS

Output: components/<name>/render/<name>.png
"""
from __future__ import annotations

import os
import sys
import time

import klayout.lay as lay

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.join(HERE, "components")
LYP = os.path.join(HERE, "gf180mcu_render.lyp")

WIDTH, HEIGHT = 1400, 1400  # output raster size (px); layout is fit to it


def _gds_path(name: str) -> str | None:
    """Prefer the compressed GDS; KLayout reads .gds.gz transparently."""
    for ext in (".gds.gz", ".gds"):
        p = os.path.join(COMPONENTS, name, "gds", f"{name}{ext}")
        if os.path.isfile(p):
            return p
    return None


def render(name: str) -> tuple[bool, float, int]:
    gds = _gds_path(name)
    if gds is None:
        return False, 0.0, 0
    out_dir = os.path.join(COMPONENTS, name, "render")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{name}.png")

    t0 = time.time()
    view = lay.LayoutView()
    view.load_layout(gds, 0)
    if os.path.isfile(LYP):
        view.load_layer_props(LYP)   # GF180MCU colors, same as the chip flow
    view.max_hier_levels = 20
    view.zoom_fit()
    view.timer()                     # let the redraw settle
    view.save_image(out, WIDTH, HEIGHT)
    dt = time.time() - t0
    return True, dt, os.path.getsize(out)


def main() -> None:
    names = sys.argv[1:] or sorted(
        d for d in os.listdir(COMPONENTS) if _gds_path(d) is not None
    )
    total = 0.0
    for name in names:
        gds = _gds_path(name)
        gds_mb = os.path.getsize(gds) / 1e6 if gds else 0
        ok, dt, png = render(name)
        total += dt
        if ok:
            print(f"  {name:32s} gds={gds_mb:6.1f}MB  ->  png={png/1e3:6.1f}KB  in {dt:5.1f}s")
        else:
            print(f"  {name:32s} (no gds)")
    print(f"\nrendered in {total:.1f}s total")


if __name__ == "__main__":
    main()
