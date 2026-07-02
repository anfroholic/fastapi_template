"""Seed generator for the Open Silicon Component Exchange prototype.

Produces a set of realistic sample component packages under ``components/``.
Each package follows the spec's 4-view layout:

    <component>/
      gds/<component>.gds                        # opaque layout (stub here)
      lef/<component>.lef                         # abstract: outline + pins  <- parsed for the SVG footprint
      vh/<component>.vh                           # black-box Verilog interface
      lib/<corner>/<component>__<corner>.lib      # timing, one dir per corner (stub here)
      component.yaml                              # catalog metadata

Run once to (re)generate the sample catalog:

    python seed_components.py

The GDS and .lib files are opaque/large in reality; here they are small text
stubs so the prototype has real files to link to and download. The LEF files
are genuine enough to parse a footprint (SIZE + PIN RECTs) from.
"""
from __future__ import annotations

import os
import textwrap

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "components")

# The nine signoff corners this design characterizes at:
#   {min, nom, max} operating point  x  {ff, tt, ss} process
# Named <point>_<process>_<temp>_<voltage>, matching the spec examples.
CORNER_MATRIX = {
    "min": {"temp": "125C", "volt_5v0": "4v50", "volt_1v8": "1v62"},
    "nom": {"temp": "025C", "volt_5v0": "5v00", "volt_1v8": "1v80"},
    "max": {"temp": "m40C", "volt_5v0": "5v50", "volt_1v8": "1v98"},
}
PROCESS = ["ff", "tt", "ss"]


def corners_for(volt_key: str) -> list[str]:
    out = []
    for point, vals in CORNER_MATRIX.items():
        for proc in PROCESS:
            out.append(f"{point}_{proc}_{vals['temp']}_{vals[volt_key]}")
    return out


# ---------------------------------------------------------------------------
# Component definitions. `pins` drives both the LEF footprint and the .vh.
# side: L/R/T/B places the pin on that edge of the block for the footprint SVG.
# ---------------------------------------------------------------------------
def pin(name, direction, side, width=1):
    return {"name": name, "dir": direction, "side": side, "width": width}


COMPONENTS = [
    {
        "name": "neural_osc",
        "description": "Tunable ring oscillator with a 6-bit digital trim for on-chip clock generation.",
        "function": "oscillator",
        "pdk": "gf180mcuD", "node": "180nm",
        "stdcell": "gf180mcu_fd_sc_mcu7t5v0",
        "volt_key": "volt_5v0",
        "clock": {"port": "clk_out", "period_ns": 40},
        "size_um": [120.0, 95.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "pass"},
        "license": "Apache-2.0",
        "source": "https://github.com/osce/neural_osc",
        "tier": "source",
        "pins": [
            pin("enable", "input", "L"), pin("trim", "input", "L", 6),
            pin("vref", "input", "L"),
            pin("clk_out", "output", "R"), pin("lock", "output", "R"),
        ],
    },
    {
        "name": "uart_tx",
        "description": "8N1 UART transmitter with 16-deep FIFO and programmable baud divisor.",
        "function": "communication",
        "pdk": "sky130A", "node": "130nm",
        "stdcell": "sky130_fd_sc_hd",
        "volt_key": "volt_1v8",
        "clock": {"port": "clk", "period_ns": 20},
        "size_um": [180.0, 140.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "pass"},
        "license": "Apache-2.0",
        "source": "https://github.com/osce/uart_tx",
        "tier": "source",
        "pins": [
            pin("clk", "input", "L"), pin("rst_n", "input", "L"),
            pin("tx_data", "input", "L", 8), pin("tx_valid", "input", "L"),
            pin("baud_div", "input", "B", 16),
            pin("tx", "output", "R"), pin("tx_ready", "output", "R"),
        ],
    },
    {
        "name": "spi_master",
        "description": "SPI master (modes 0-3) with configurable clock divider and 4 chip selects.",
        "function": "communication",
        "pdk": "sky130A", "node": "130nm",
        "stdcell": "sky130_fd_sc_hd",
        "volt_key": "volt_1v8",
        "clock": {"port": "clk", "period_ns": 15},
        "size_um": [210.0, 160.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "warn"},
        "license": "BSD-3-Clause",
        "source": "https://github.com/osce/spi_master",
        "tier": "binary",
        "pins": [
            pin("clk", "input", "L"), pin("rst_n", "input", "L"),
            pin("mosi_data", "input", "L", 8), pin("start", "input", "L"),
            pin("sclk", "output", "R"), pin("mosi", "output", "R"),
            pin("miso", "input", "T"), pin("cs_n", "output", "R", 4),
        ],
    },
    {
        "name": "sram_1kb",
        "description": "1KB single-port SRAM macro, 256x32, with byte-write enables.",
        "function": "memory",
        "pdk": "sky130A", "node": "130nm",
        "stdcell": "sky130_fd_sc_hd",
        "volt_key": "volt_1v8",
        "clock": {"port": "clk", "period_ns": 8},
        "size_um": [340.0, 300.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "pass"},
        "license": "OpenRAM",
        "source": "https://github.com/osce/sram_1kb",
        "tier": "binary",
        "pins": [
            pin("clk", "input", "L"), pin("cs_n", "input", "L"),
            pin("we_n", "input", "L", 4), pin("addr", "input", "L", 8),
            pin("din", "input", "B", 32),
            pin("dout", "output", "T", 32),
        ],
    },
    {
        "name": "pll_100m",
        "description": "Integer-N charge-pump PLL, 10-100 MHz output from a 10 MHz reference.",
        "function": "clock",
        "pdk": "gf180mcuD", "node": "180nm",
        "stdcell": "gf180mcu_fd_sc_mcu7t5v0",
        "volt_key": "volt_5v0",
        "clock": {"port": "clk_out", "period_ns": 10},
        "size_um": [260.0, 220.0],
        "signoff": {"drc": "clean", "lvs": "warn", "setup": "pass", "hold": "pass"},
        "license": "CERN-OHL-S-2.0",
        "source": "https://github.com/osce/pll_100m",
        "tier": "source",
        "pins": [
            pin("ref_clk", "input", "L"), pin("div_n", "input", "L", 7),
            pin("enable", "input", "L"), pin("vdd_a", "input", "B"),
            pin("clk_out", "output", "R"), pin("locked", "output", "R"),
        ],
    },
    {
        "name": "i2c_slave",
        "description": "I2C slave with 7-bit address match, clock stretching, and a 32-byte register file.",
        "function": "communication",
        "pdk": "gf180mcuD", "node": "180nm",
        "stdcell": "gf180mcu_fd_sc_mcu7t5v0",
        "volt_key": "volt_5v0",
        "clock": {"port": "clk", "period_ns": 25},
        "size_um": [190.0, 150.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "pass"},
        "license": "Apache-2.0",
        "source": "https://github.com/osce/i2c_slave",
        "tier": "source",
        "pins": [
            pin("clk", "input", "L"), pin("rst_n", "input", "L"),
            pin("addr", "input", "L", 7),
            pin("scl", "input", "T"), pin("sda", "input", "B"),
            pin("irq", "output", "R"), pin("reg_out", "output", "R", 8),
        ],
    },
    {
        "name": "rv32i_alu",
        "description": "RV32I integer ALU: add/sub/shift/logic/compare, single-cycle, no multiply.",
        "function": "compute",
        "pdk": "sky130A", "node": "130nm",
        "stdcell": "sky130_fd_sc_hd",
        "volt_key": "volt_1v8",
        "clock": {"port": "clk", "period_ns": 5},
        "size_um": [230.0, 180.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "warn", "hold": "pass"},
        "license": "Apache-2.0",
        "source": "https://github.com/osce/rv32i_alu",
        "tier": "source",
        "pins": [
            pin("clk", "input", "L"), pin("op", "input", "L", 4),
            pin("a", "input", "L", 32), pin("b", "input", "B", 32),
            pin("result", "output", "R", 32), pin("zero", "output", "R"),
        ],
    },
    {
        "name": "fir_filter",
        "description": "8-tap fixed-point FIR filter, reloadable coefficients, 16-bit datapath.",
        "function": "dsp",
        "pdk": "sky130A", "node": "130nm",
        "stdcell": "sky130_fd_sc_hd",
        "volt_key": "volt_1v8",
        "clock": {"port": "clk", "period_ns": 6},
        "size_um": [300.0, 240.0],
        "signoff": {"drc": "clean", "lvs": "clean", "setup": "pass", "hold": "pass"},
        "license": "MIT",
        "source": "https://github.com/osce/fir_filter",
        "tier": "binary",
        "pins": [
            pin("clk", "input", "L"), pin("rst_n", "input", "L"),
            pin("sample_in", "input", "L", 16), pin("coef", "input", "B", 16),
            pin("coef_we", "input", "L"),
            pin("sample_out", "output", "R", 16), pin("valid", "output", "R"),
        ],
    },
]


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------
def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        f.write(content)


def bus(width: int) -> str:
    return "" if width == 1 else f"[{width - 1}:0] "


def gen_lef(c: dict) -> str:
    """A minimal but genuinely parseable LEF: MACRO SIZE + one PIN/PORT/RECT each.

    Pins are distributed along the edge given by their `side`, so the parsed
    footprint reflects the declared interface.
    """
    w, h = c["size_um"]
    lines = [
        "VERSION 5.8 ;",
        "BUSBITCHARS \"[]\" ;",
        "",
        f"MACRO {c['name']}",
        "  CLASS BLOCK ;",
        "  ORIGIN 0 0 ;",
        f"  SIZE {w:.3f} BY {h:.3f} ;",
    ]
    # group pins per side and space them out along that edge
    sides: dict[str, list[dict]] = {"L": [], "R": [], "T": [], "B": []}
    for p in c["pins"]:
        sides[p["side"]].append(p)
    pw = 2.0  # pin rect footprint, um
    for side, plist in sides.items():
        n = len(plist)
        for i, p in enumerate(plist):
            frac = (i + 1) / (n + 1)
            if side in ("L", "R"):
                y = round(frac * h, 3)
                x = 0.0 if side == "L" else round(w - pw, 3)
                rect = (x, round(y - pw / 2, 3), round(x + pw, 3), round(y + pw / 2, 3))
            else:
                x = round(frac * w, 3)
                yb = 0.0 if side == "B" else round(h - pw, 3)
                rect = (round(x - pw / 2, 3), yb, round(x + pw / 2, 3), round(yb + pw, 3))
            use = "SIGNAL"
            lines += [
                f"  PIN {p['name']}",
                f"    DIRECTION {p['dir'].upper()} ;",
                f"    USE {use} ;",
                "    PORT",
                "      LAYER met2 ;",
                f"        RECT {rect[0]:.3f} {rect[1]:.3f} {rect[2]:.3f} {rect[3]:.3f} ;",
                "    END",
                f"  END {p['name']}",
            ]
    lines += [
        "  OBS",
        "    LAYER met1 ;",
        f"      RECT 2.000 2.000 {w - 2:.3f} {h - 2:.3f} ;",
        "  END",
        f"END {c['name']}",
        "",
        "END LIBRARY",
        "",
    ]
    return "\n".join(lines)


def gen_vh(c: dict) -> str:
    ports = []
    for p in c["pins"]:
        ports.append(f"  {p['dir']:<6} wire {bus(p['width'])}{p['name']}")
    body = ",\n".join(ports)
    return (
        f"// Black-box interface for {c['name']} ({c['function']}).\n"
        f"// Ports only -- internals are sealed. Lets parent synthesis elaborate.\n"
        f"module {c['name']} (\n{body}\n);\nendmodule\n"
    )


def gen_gds_stub(c: dict) -> str:
    return (
        f"; GDSII placeholder for {c['name']}.\n"
        f"; The real artifact is opaque binary mask geometry ({c['size_um'][0]}x"
        f"{c['size_um'][1]} um) merged at final streamout.\n"
        f"; In this prototype the layout is intentionally a sealed black box.\n"
    )


def gen_lib_stub(c: dict, corner: str) -> str:
    return textwrap.dedent(
        f"""\
        /* Liberty timing/power stub for {c['name']} at corner {corner}. */
        library ({c['name']}__{corner}) {{
          delay_model : table_lookup ;
          time_unit : "1ns" ;
          voltage_unit : "1V" ;
          cell ({c['name']}) {{
            /* pin timing arcs omitted in this prototype stub */
          }}
        }}
        """
    )


def gen_yaml(c: dict) -> str:
    corners = corners_for(c["volt_key"])
    meta = {
        "name": c["name"],
        "description": c["description"],
        "function": c["function"],
        "pdk": c["pdk"],
        "node": c["node"],
        "stdcell": c["stdcell"],
        "corners": corners,
        "clock": c["clock"],
        "size_um": c["size_um"],
        "signoff": c["signoff"],
        "license": c["license"],
        "source": c["source"],
        "tier": c["tier"],
    }
    return yaml.safe_dump(meta, sort_keys=False, default_flow_style=False)


def main() -> None:
    for c in COMPONENTS:
        base = os.path.join(ROOT, c["name"])
        write(os.path.join(base, "component.yaml"), gen_yaml(c))
        write(os.path.join(base, "lef", f"{c['name']}.lef"), gen_lef(c))
        write(os.path.join(base, "vh", f"{c['name']}.vh"), gen_vh(c))
        write(os.path.join(base, "gds", f"{c['name']}.gds"), gen_gds_stub(c))
        for corner in corners_for(c["volt_key"]):
            write(
                os.path.join(base, "lib", corner, f"{c['name']}__{corner}.lib"),
                gen_lib_stub(c, corner),
            )
        print(f"seeded {c['name']}")
    print(f"\n{len(COMPONENTS)} components written to {ROOT}")


if __name__ == "__main__":
    main()
