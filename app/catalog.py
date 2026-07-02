"""Loads component packages from ``components/`` into in-memory catalog objects.

Each package's ``component.yaml`` is the source of truth. We enrich it with the
parsed LEF footprint, a computed corner-coverage matrix, and a copy-paste
``MACROS:`` integration snippet -- everything the templates need to render.

Loaded once at import; the ``--reload`` dev flag re-imports on file save.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from lef import Macro, footprint_svg, parse_lef

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS_DIR = os.path.join(HERE, "components")

# Emoji glyphs keep the "playful / Thingiverse" browse feel without image assets.
FUNCTION_ICONS = {
    "audio": "🎛️",
    "oscillator": "〰️",
    "communication": "📡",
    "memory": "🧠",
    "clock": "⏱️",
    "compute": "🧮",
    "dsp": "🎚️",
    "identifier": "🔖",
    "branding": "✨",
}

# The signoff checks we surface as traffic-light pips, in display order.
SIGNOFF_CHECKS = ["drc", "lvs", "setup", "hold"]

# Corner matrix axes.
CORNER_POINTS = ["min", "nom", "max"]          # operating point (columns)
CORNER_PROCESS = ["ff", "tt", "ss"]            # process skew (rows)


@dataclass
class Component:
    name: str
    description: str
    function: str
    pdk: str
    node: str
    stdcell: str
    corners: list[str]
    clock: dict
    size_um: list[float]
    signoff: dict
    license: str
    source: str
    tier: str
    path: str
    macro: Macro | None = None
    raw: dict = field(default_factory=dict)

    # -- derived display helpers -------------------------------------------
    @property
    def icon(self) -> str:
        return FUNCTION_ICONS.get(self.function, "🔩")

    @property
    def width_um(self) -> float:
        return self.size_um[0]

    @property
    def height_um(self) -> float:
        return self.size_um[1]

    @property
    def area_um2(self) -> float:
        return self.size_um[0] * self.size_um[1]

    @property
    def freq_mhz(self) -> float:
        p = self.clock.get("period_ns")
        return round(1000.0 / p, 1) if p else 0.0

    @property
    def clock_label(self) -> str:
        return f"{self.freq_mhz} MHz" if self.clock.get("period_ns") else "async"

    @property
    def pin_count(self) -> int:
        return len(self.macro.pins) if self.macro else 0

    @property
    def power_pin_count(self) -> int:
        return len(self.macro.power_pins) if self.macro else 0

    @property
    def has_audio(self) -> bool:
        return bool(self.raw.get("preview_audio")) and os.path.isfile(
            os.path.join(HERE, "static", "previews", f"{self.name}.wav")
        )

    @property
    def audio_url(self) -> str:
        return f"/static/previews/{self.name}.wav"

    @property
    def render_path(self) -> str | None:
        """Path to a rendered layout PNG (the 'GDS view'), if one exists."""
        p = os.path.join(self.path, "render", f"{self.name}.png")
        return p if os.path.isfile(p) else None

    @property
    def has_render(self) -> bool:
        return self.render_path is not None

    @property
    def signoff_ok(self) -> bool:
        return all(v == "clean" or v == "pass" for v in self.signoff.values())

    @property
    def corner_count(self) -> int:
        return len(self.corners)

    @property
    def corner_matrix(self) -> list[list[dict]]:
        """3x3 grid [process rows][point cols] -> {present, name}.

        Coverage is derived by matching the point/process tokens embedded in
        each corner name (e.g. "min_ss_125C_4v50").
        """
        grid = []
        for proc in CORNER_PROCESS:
            row = []
            for point in CORNER_POINTS:
                match = next(
                    (c for c in self.corners
                     if c.startswith(point + "_") and f"_{proc}_" in c),
                    None,
                )
                row.append({"present": match is not None, "name": match, "point": point, "process": proc})
            row_meta = {"process": proc, "cells": row}
            grid.append(row_meta)
        return grid

    def footprint_svg(self, labels: bool = True) -> str:
        return footprint_svg(self.macro, labels=labels) if self.macro else ""

    @property
    def gds_rel(self) -> str:
        """Relative path to the shipped GDS (compressed if present)."""
        for ext in (".gds.gz", ".gds"):
            if os.path.isfile(os.path.join(self.path, "gds", f"{self.name}{ext}")):
                return f"gds/{self.name}{ext}"
        return f"gds/{self.name}.gds"

    @property
    def macros_snippet(self) -> str:
        """The payoff: drop this into a flow's MACROS: list and it just works."""
        return (
            "MACROS:\n"
            f"  - name: {self.name}\n"
            f"    pdk: {self.pdk}\n"
            f"    lef: lef/{self.name}.lef\n"
            f"    gds: {self.gds_rel}\n"
            f"    lib: lib/*/{self.name}__*.lib\n"
        )


def _load_one(name: str) -> Component | None:
    base = os.path.join(COMPONENTS_DIR, name)
    yaml_path = os.path.join(base, "component.yaml")
    if not os.path.isfile(yaml_path):
        return None
    with open(yaml_path) as f:
        meta = yaml.safe_load(f)

    macro = None
    lef_path = os.path.join(base, "lef", f"{name}.lef")
    if os.path.isfile(lef_path):
        with open(lef_path) as f:
            macro = parse_lef(f.read())

    return Component(
        name=meta["name"],
        description=meta.get("description", ""),
        function=meta.get("function", "misc"),
        pdk=meta.get("pdk", ""),
        node=meta.get("node", ""),
        stdcell=meta.get("stdcell", ""),
        corners=meta.get("corners", []),
        clock=meta.get("clock", {}) or {},
        size_um=meta.get("size_um", [0, 0]),
        signoff=meta.get("signoff", {}) or {},
        license=meta.get("license", ""),
        source=meta.get("source", ""),
        tier=meta.get("tier", "binary"),
        path=base,
        macro=macro,
        raw=meta,
    )


def load_components() -> list[Component]:
    if not os.path.isdir(COMPONENTS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(COMPONENTS_DIR)):
        if os.path.isdir(os.path.join(COMPONENTS_DIR, name)):
            comp = _load_one(name)
            if comp:
                out.append(comp)
    return out


class Catalog:
    """In-memory index over the loaded components with simple facet filtering."""

    def __init__(self, components: list[Component]):
        self.components = components
        self.by_name = {c.name: c for c in components}

    def get(self, name: str) -> Component | None:
        return self.by_name.get(name)

    def facets(self) -> dict[str, list[str]]:
        return {
            "function": sorted({c.function for c in self.components}),
            "pdk": sorted({c.pdk for c in self.components}),
            "node": sorted({c.node for c in self.components}),
            "license": sorted({c.license for c in self.components}),
        }

    def filter(
        self,
        q: str | None = None,
        function: str | None = None,
        pdk: str | None = None,
        node: str | None = None,
        license: str | None = None,
        signoff_clean: bool = False,
        sort: str = "name",
    ) -> list[Component]:
        items = self.components
        if q:
            ql = q.lower()
            items = [c for c in items if ql in c.name.lower() or ql in c.description.lower()]
        if function:
            items = [c for c in items if c.function == function]
        if pdk:
            items = [c for c in items if c.pdk == pdk]
        if node:
            items = [c for c in items if c.node == node]
        if license:
            items = [c for c in items if c.license == license]
        if signoff_clean:
            items = [c for c in items if c.signoff_ok]

        keys = {
            "name": lambda c: c.name,
            "area": lambda c: c.area_um2,
            "freq": lambda c: -c.freq_mhz,
            "corners": lambda c: -c.corner_count,
        }
        return sorted(items, key=keys.get(sort, keys["name"]))


CATALOG = Catalog(load_components())
