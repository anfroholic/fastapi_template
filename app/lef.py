"""Minimal LEF reader + SVG footprint renderer.

A GDS layout is opaque binary, but the LEF abstract is text: it carries the
block outline (``SIZE w BY h``) and pin locations (``PIN <name> ... RECT ...``).
That is exactly enough to draw a meaningful "footprint" thumbnail -- a labeled
box with pins on its edges -- which is the catalog's signature visual.

This is a pragmatic parser for the subset of LEF the seed generator emits, not a
full LEF grammar. It is tolerant: anything it does not recognize is ignored.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field


@dataclass
class Pin:
    name: str
    direction: str = "inout"
    use: str = "signal"
    rect: tuple[float, float, float, float] | None = None  # (x1, y1, x2, y2) um
    width: int = 1  # bus width once grouped (e.g. pitch[9:0] -> 10)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.rect  # type: ignore[misc]
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def label(self) -> str:
        return f"{self.name}[{self.width - 1}:0]" if self.width > 1 else self.name


@dataclass
class Macro:
    name: str
    width: float = 0.0
    height: float = 0.0
    pins: list[Pin] = field(default_factory=list)        # signal pins, bus-grouped
    power_pins: list[Pin] = field(default_factory=list)   # VDD/VSS/... shown separately


_SIZE_RE = re.compile(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", re.I)
_RECT_RE = re.compile(r"RECT\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)", re.I)
_BUS_RE = re.compile(r"^(.*?)\[(\d+)\]$")  # split "pitch[9]" -> ("pitch", 9)
_POWER_NAMES = {"vdd", "vss", "vgnd", "vpwr", "vccd", "vssd", "vdda", "vssa", "gnd"}


def _is_power(pin: Pin) -> bool:
    return pin.use in ("power", "ground") or pin.name.lower() in _POWER_NAMES


def _group_buses(pins: list[Pin]) -> list[Pin]:
    """Collapse pins like foo[0..9] into one representative bus pin.

    The representative sits at the centroid of its members so its footprint nub
    lands where the bus actually is, and its width is the member count.
    """
    groups: dict[str, list[Pin]] = {}
    order: list[str] = []
    for p in pins:
        m = _BUS_RE.match(p.name)
        base = m.group(1) if m else p.name
        if base not in groups:
            groups[base] = []
            order.append(base)
        groups[base].append(p)

    out = []
    for base in order:
        members = [p for p in groups[base] if p.rect is not None]
        if not members:
            continue
        cx = sum(p.center[0] for p in members) / len(members)
        cy = sum(p.center[1] for p in members) / len(members)
        rep = Pin(
            name=base,
            direction=members[0].direction,
            use=members[0].use,
            rect=(cx - 1, cy - 1, cx + 1, cy + 1),
            width=len(members),
        )
        out.append(rep)
    return out


def parse_lef(text: str) -> Macro | None:
    """Parse the first MACRO in a LEF string. Returns None if none found."""
    macro: Macro | None = None
    cur_pin: Pin | None = None
    in_pin = False
    raw_pins: list[Pin] = []

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("MACRO "):
            macro = Macro(name=line.split()[1])
        elif macro is None:
            continue
        elif (m := _SIZE_RE.search(line)):
            macro.width, macro.height = float(m.group(1)), float(m.group(2))
        elif line.startswith("PIN "):
            in_pin = True
            cur_pin = Pin(name=line.split()[1])
        elif in_pin and line.startswith("DIRECTION"):
            cur_pin.direction = line.split()[1].lower()  # type: ignore[union-attr]
        elif in_pin and line.startswith("USE"):
            cur_pin.use = line.split()[1].lower()  # type: ignore[union-attr]
        elif in_pin and line.startswith("RECT") and cur_pin and cur_pin.rect is None:
            r = _RECT_RE.search(line)
            if r:
                cur_pin.rect = tuple(float(x) for x in r.groups())  # type: ignore[assignment]
        elif line.startswith("END ") and in_pin and cur_pin and line.split()[1] == cur_pin.name:
            if cur_pin.rect is not None:
                raw_pins.append(cur_pin)
            in_pin = False
            cur_pin = None

    if macro is None:
        return None

    signal = [p for p in raw_pins if not _is_power(p)]
    macro.pins = _group_buses(signal)
    macro.power_pins = _group_buses([p for p in raw_pins if _is_power(p)])
    return macro


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------
_INPUT_COLOR = "#2a9d8f"
_OUTPUT_COLOR = "#e76f51"
_INOUT_COLOR = "#e9c46a"


def _pin_color(direction: str) -> str:
    if direction.startswith("in") and direction != "inout":
        return _INPUT_COLOR
    if direction.startswith("out"):
        return _OUTPUT_COLOR
    return _INOUT_COLOR


def footprint_svg(macro: Macro, *, labels: bool = True, pad: float = 34.0) -> str:
    """Render the macro as an SVG footprint. Scaled to a ~260px-wide viewbox.

    labels=False produces a compact, unlabeled version suitable for cards.
    """
    if macro.width <= 0 or macro.height <= 0:
        return ""

    # scale um -> px so the longer side is ~200px
    target = 200.0
    scale = target / max(macro.width, macro.height)
    bw, bh = macro.width * scale, macro.height * scale
    W, H = bw + pad * 2, bh + pad * 2

    def sx(x: float) -> float:
        return pad + x * scale

    def sy(y: float) -> float:
        # LEF origin is bottom-left; SVG is top-left -> flip Y
        return pad + (macro.height - y) * scale

    parts = [
        f'<svg viewBox="0 0 {W:.1f} {H:.1f}" class="footprint" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Footprint of {html.escape(macro.name)}">',
        # die body
        f'<rect x="{sx(0):.1f}" y="{sy(macro.height):.1f}" width="{bw:.1f}" '
        f'height="{bh:.1f}" rx="6" class="fp-body"/>',
        # pin-1 corner notch (bottom-left)
        f'<circle cx="{sx(0)+9:.1f}" cy="{sy(0)-9:.1f}" r="3" class="fp-notch"/>',
    ]

    for p in macro.pins:
        cx, cy = p.center
        px, py = sx(cx), sy(cy)
        color = _pin_color(p.direction)
        # nub sticking out of the edge toward nearest border
        left = abs(cx - 0) < abs(cx - macro.width)
        near_v = min(cx, macro.width - cx)
        near_h = min(cy, macro.height - cy)
        parts.append(
            f'<rect x="{px-3.5:.1f}" y="{py-3.5:.1f}" width="7" height="7" '
            f'rx="1.5" fill="{color}"/>'
        )
        if labels:
            if near_v <= near_h:  # left/right edge
                if left:
                    tx, anchor = px - 6, "end"
                else:
                    tx, anchor = px + 6, "start"
                parts.append(
                    f'<text x="{tx:.1f}" y="{py+3:.1f}" text-anchor="{anchor}" '
                    f'class="fp-label">{html.escape(p.label)}</text>'
                )
            else:  # top/bottom edge -> rotate label
                ty = py - 6 if cy > macro.height / 2 else py + 6
                anchor = "start" if cy > macro.height / 2 else "end"
                parts.append(
                    f'<text x="{px+3:.1f}" y="{ty:.1f}" text-anchor="{anchor}" '
                    f'class="fp-label" transform="rotate(-90 {px:.1f} {ty:.1f})">'
                    f'{html.escape(p.label)}</text>'
                )

    # macro name centered in the body
    parts.append(
        f'<text x="{sx(macro.width/2):.1f}" y="{sy(macro.height/2):.1f}" '
        f'text-anchor="middle" class="fp-title">{html.escape(macro.name)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
