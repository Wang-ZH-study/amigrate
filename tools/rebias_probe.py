#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PVT 修复探针：改偏置电阻 Rb 与补偿电容 Cc，在最坏角（ss/0.9/-40）与标称点看
gain / UGB / PM / power 的变化。

用法：python tools/rebias_probe.py --gen   # 生成网表
      python tools/rebias_probe.py --parse --raw runs/2026-11-25-pvt/probe/raw
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pvt_sweep import parse_ac, parse_op, DEVS  # noqa: E402

OUT = ROOT / "runs" / "2026-11-25-pvt" / "probe"
INCLUDE = 'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section={section}"'

# (name, proc, vdd, temp, Rb, Cc)
CASES = [
    ("base_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "900f", 1.0),
    ("base_tt_nom", "tt", 1.80, 27.0, "19.31K", "900f", 1.0),
    ("fixA_ss_lo_cold", "ss", 1.62, -40.0, "8K", "600f", 1.0),
    ("fixA_tt_nom", "tt", 1.80, 27.0, "8K", "600f", 1.0),
    ("fixB_ss_lo_cold", "ss", 1.62, -40.0, "6K", "450f", 1.0),
    ("fixB_tt_nom", "tt", 1.80, 27.0, "6K", "450f", 1.0),
    ("w4_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "900f", 4.0),
    ("w4_tt_nom", "tt", 1.80, 27.0, "19.31K", "900f", 4.0),
    ("w16_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "900f", 16.0),
    ("w16_tt_nom", "tt", 1.80, 27.0, "19.31K", "900f", 16.0),
    ("w16c12_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.2p", 16.0),
    ("w16c12_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.2p", 16.0),
    ("w8c12_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.2p", 8.0),
    ("w8c12_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.2p", 8.0),
    ("w16c15_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.5p", 16.0),
    ("w24c15_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.5p", 24.0),
    ("w24c15_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.5p", 24.0),
    ("w32c15_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.5p", 32.0),
    ("w32c15_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.5p", 32.0),
    ("w32c18_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.8p", 32.0),
    ("w32c18_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.8p", 32.0),
]


EXTRA = [
    ("w32c18r25_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.8p", 32.0, "2.5K"),
    ("w32c18r25_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.8p", 32.0, "2.5K"),
    ("w32c18r40_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.8p", 32.0, "4K"),
    ("w32c18r40_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.8p", 32.0, "4K"),
    ("w32c15r25_ss_lo_cold", "ss", 1.62, -40.0, "19.31K", "1.5p", 32.0, "2.5K"),
    ("w32c15r25_tt_nom", "tt", 1.80, 27.0, "19.31K", "1.5p", 32.0, "2.5K"),
]
     
def netlist(proc: str, vdd: float, temp: float, rb: str, cc: str, wscale: float = 1.0, rz: str = "1.25K") -> str:
    vcm = vdd / 2
    lines = [
        f"// probe proc={proc} vdd={vdd:g} temp={temp:g} Rb={rb} Cc={cc}",
        "simulator lang=spectre",
        "global 0",
        INCLUDE.format(section=proc),
        f"simulatorOptions options temp={temp:g} tnom=27",
        "",
        "subckt OPA_D OUT VDD VINM VINP VSS",
    ]
    for name, terms, model, w, l in DEVS:
        if wscale != 1.0 and name in ("M1", "M2"):
            w = f"{float(w[:-1]) * wscale:.4g}u"
        lines.append(f"    {name} ({terms}) {model} w={w} l={l}")
    lines += [
        f"    Rz (OUT NZ) resistor r={rz}",
        f"    Rb (VBP VSS) resistor r={rb}",
        f"    C0 (VX NZ) capacitor c={cc}",
        "ends OPA_D",
        "",
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        f"Vdd (vdd 0) vsource dc={vdd:g}",
        f"Vinp (vinp 0) vsource dc={vcm:g} mag=1",
        f"Vcm (vcm 0) vsource dc={vcm:g}",
        "Lfb (OUT vinn) inductor l=1G",
        "Riso (vinn vcm) resistor r=1k",
        "",
        "op1 dc",
        "ac1 ac start=1 stop=200M dec=10",
        "save OUT Vdd:p",
        "",
    ]
    return "\n".join(lines)


def gen() -> int:
    nets = OUT / "nets"
    nets.mkdir(parents=True, exist_ok=True)
    for name, proc, vdd, temp, rb, cc, wscale in CASES:
        (nets / f"{name}.scs").write_text(netlist(proc, vdd, temp, rb, cc, wscale), encoding="utf-8", newline="\n")
    for name, proc, vdd, temp, rb, cc, wscale, rz in EXTRA:
        (nets / f"{name}.scs").write_text(netlist(proc, vdd, temp, rb, cc, wscale, rz), encoding="utf-8", newline="\n")
    print(f"生成 {len(CASES)} 个探针网表 → {nets}")
    return 0


def metrics(d: Path) -> dict:
    base = d / "net.raw" if (d / "net.raw").is_dir() else d
    r: dict = {}
    ac = base / "ac1.ac"
    if ac.exists():
        freq, out = parse_ac(ac)
        if out:
            r["gain"] = 20 * math.log10(abs(out[0]))
            z = dict(zip(freq, out))
            rows = [(f, 20 * math.log10(abs(v))) for f, v in zip(freq, out) if abs(v) > 0]
            for (f1, g1), (f2, g2) in zip(rows, rows[1:]):
                if g1 > 0 >= g2:
                    t = g1 / (g1 - g2) if g1 != g2 else 0
                    ugf = 10 ** (math.log10(f1) + t * (math.log10(f2) - math.log10(f1)))
                    a1 = math.degrees(__import__("cmath").phase(z[f1]))
                    a2 = math.degrees(__import__("cmath").phase(z[f2]))
                    ang = a1 + t * (a2 - a1)
                    r["gbw"] = ugf / 1e6
                    r["pm"] = 180 + ang if ang < 0 else 180 - ang
                    break
    op = base / "op1.dc"
    if op.exists():
        sig = parse_op(op)
        if "Vdd:p" in sig:
            r["power"] = abs(sig["Vdd:p"]) * 1.8 * 1e6
    return r


def parse(raw: Path) -> int:
    print(f"{'case':22s}{'gain(dB)':>10s}{'UGF(MHz)':>10s}{'PM(deg)':>9s}{'power(uW)':>11s}")
    for d in sorted(raw.iterdir()):
        if not d.is_dir():
            continue
        m = metrics(d)
        if not m:
            continue
        print(f"{d.name:22s}{m.get('gain', float('nan')):10.2f}{m.get('gbw', float('nan')):10.2f}"
              f"{m.get('pm', float('nan')):9.1f}{m.get('power', float('nan')):11.0f}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--raw", type=Path, default=OUT / "raw")
    a = ap.parse_args(argv)
    if a.gen:
        return gen()
    if a.parse:
        return parse(a.raw)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))