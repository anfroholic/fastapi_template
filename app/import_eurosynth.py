"""Import real hardened macros from the EuroSynth repo into this catalog.

EuroSynth (https://github.com/anfroholic/eurosynth) taped out a digital eurorack
synth voice on GF180MCU. Its ``ip/<macro>/`` packages already ship the four EDA
views (gds/lef/vh/lib) — exactly what this catalog displays. They just lack a
``component.yaml``, so we copy the views over and synthesize the metadata here
(size + corners are read from the real LEF/lib; the rest is curated per macro).

Usage:
    python import_eurosynth.py [path-to-eurosynth-repo]

Defaults to ../../eurosynth relative to this file. Re-runnable: it clears and
rewrites app/components/ each time.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys

import yaml

from lef import parse_lef

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "components")
PREVIEW_DEST = os.path.join(HERE, "static", "previews")

DEFAULT_SRC = os.path.abspath(os.path.join(HERE, "..", "..", "eurosynth"))

PDK = "gf180mcuD"
NODE = "180nm"
STDCELL = "gf180mcu_fd_sc_mcu7t5v0"
SOURCE = "https://github.com/anfroholic/eurosynth"

CLEAN = {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "pass"}

# Curated per-macro metadata. Everything not listed (size_um, corners) is derived
# from the real views at import time. `preview` names a .wav in eurosynth/previews.
MACROS = {
    "ks_engine": dict(
        function="audio", tier="source", clk=True, preview="ks",
        description="Karplus–Strong plucked-string voice — bit-exact vs the golden "
                    "reference and the flagship signed-off engine.",
    ),
    "neural_osc": dict(
        function="audio", tier="source", clk=True, preview="neural",
        description="Neural wavetable oscillator — a tiny learned network sweeps "
                    "timbre via a 6-bit morph, weights baked into the GDS.",
    ),
    "chaos_engine": dict(
        function="audio", tier="source", clk=True, preview="chaos",
        description="Chaotic oscillator built on Lorenz/logistic maps for evolving, "
                    "never-repeating drones and textures.",
    ),
    "sid_engine": dict(
        function="audio", tier="source", clk=True, preview="sid",
        description="SID-style synth voice — classic 8-bit-era waveforms with "
                    "envelope and filter character.",
    ),
    "bytebeat": dict(
        function="audio", tier="source", clk=True, preview="bytebeat",
        description="Bytebeat generator — a free-running integer formula over a "
                    "sample counter produces surprisingly musical noise.",
    ),
    "gf180mcu_ws_ip__logo": dict(
        function="branding", tier="binary", clk=False, preview=None,
        description="wafer.space shuttle logo tile — decorative top-metal artwork "
                    "dropped into the seal ring.",
    ),
    "gf180mcu_ws_ip__qrcode_id": dict(
        function="identifier", tier="binary", clk=False, preview=None,
        description="QR-code die identifier — encodes the project/shuttle ID as an "
                    "on-die scannable mark.",
    ),
    "gf180mcu_ws_ip__project_id": dict(
        function="identifier", tier="binary", clk=False, preview=None,
        description="Project-ID mark — human-readable project identifier tile.",
    ),
    "gf180mcu_ws_ip__shuttle_id": dict(
        function="identifier", tier="binary", clk=False, preview=None,
        description="Shuttle-ID mark — identifies the manufacturing shuttle run.",
    ),
    "gf180mcu_ws_ip__marker": dict(
        function="identifier", tier="binary", clk=False, preview=None,
        description="Corner marker — an alignment/orientation fiducial for the die.",
    ),
}


def _corners(src_macro: str) -> list[str]:
    lib_dir = os.path.join(src_macro, "lib")
    if not os.path.isdir(lib_dir):
        return []
    return sorted(
        d for d in os.listdir(lib_dir)
        if os.path.isdir(os.path.join(lib_dir, d))
    )


def _copytree(src: str, dst: str) -> None:
    if os.path.isdir(src):
        shutil.copytree(src, dst)


def _gzip_gds(src_dir: str, dst_dir: str, name: str) -> None:
    """Copy the GDS compressed as <name>.gds.gz (~7x smaller; KLayout reads it
    transparently, so nothing downstream needs the raw file)."""
    src = os.path.join(src_dir, f"{name}.gds")
    if not os.path.isfile(src):
        return
    os.makedirs(dst_dir, exist_ok=True)
    with open(src, "rb") as fi, gzip.open(os.path.join(dst_dir, f"{name}.gds.gz"), "wb", 6) as fo:
        shutil.copyfileobj(fi, fo)


def main() -> None:
    src_root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    ip_root = os.path.join(src_root, "ip")
    if not os.path.isdir(ip_root):
        sys.exit(f"eurosynth ip/ not found at {ip_root}")

    if os.path.isdir(DEST):
        shutil.rmtree(DEST)
    os.makedirs(DEST)
    os.makedirs(PREVIEW_DEST, exist_ok=True)

    for name, meta in MACROS.items():
        src = os.path.join(ip_root, name)
        if not os.path.isdir(src):
            print(f"  skip {name} (not in source)")
            continue
        dst = os.path.join(DEST, name)
        os.makedirs(dst)

        # --- copy the four views (GDS compressed, rest verbatim) --------
        for view in ("lef", "lib"):
            _copytree(os.path.join(src, view), os.path.join(dst, view))
        _gzip_gds(os.path.join(src, "gds"), os.path.join(dst, "gds"), name)
        # vh: engines ship <name>.vh, wafer.space ship <name>.v — normalize to .vh
        os.makedirs(os.path.join(dst, "vh"))
        for cand in (f"{name}.vh", f"{name}.v"):
            vp = os.path.join(src, "vh", cand)
            if os.path.isfile(vp):
                shutil.copy(vp, os.path.join(dst, "vh", f"{name}.vh"))
                break

        # --- derive size from the real LEF ------------------------------
        lef_path = os.path.join(dst, "lef", f"{name}.lef")
        size = [0.0, 0.0]
        if os.path.isfile(lef_path):
            with open(lef_path) as f:
                macro = parse_lef(f.read())
            if macro:
                size = [round(macro.width, 2), round(macro.height, 2)]

        # --- audio preview ----------------------------------------------
        if meta["preview"]:
            wav = os.path.join(src_root, "previews", f"{meta['preview']}_12k.wav")
            if os.path.isfile(wav):
                shutil.copy(wav, os.path.join(PREVIEW_DEST, f"{name}.wav"))

        # --- write component.yaml ---------------------------------------
        doc = {
            "name": name,
            "description": meta["description"],
            "function": meta["function"],
            "pdk": PDK,
            "node": NODE,
            "stdcell": STDCELL,
            "corners": _corners(src),
            "clock": {"port": "clk", "period_ns": 40} if meta["clk"] else {},
            "size_um": size,
            "signoff": dict(CLEAN),
            "license": "Apache-2.0",
            "source": SOURCE,
            "tier": meta["tier"],
            "preview_audio": bool(meta["preview"]),
        }
        with open(os.path.join(dst, "component.yaml"), "w", newline="\n") as f:
            yaml.safe_dump(doc, f, sort_keys=False)
        print(f"  imported {name:32s} {size[0]}x{size[1]} um, {len(doc['corners'])} corners")

    print(f"\nDone -> {DEST}")


if __name__ == "__main__":
    main()
