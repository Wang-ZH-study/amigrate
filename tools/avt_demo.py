#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打印 OPA_D v2 各管的失配容忍带（与华为专利口径一致：σ(ΔVt)=Avt/√(WL)，3σ）。"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve_lw import Lut, sigma_vt_mV, band_from_avt  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LUT = ROOT / "runs" / "2026-11-25-lut-build" / "13mmrf_io18" / "lut_13mmrf_io18.csv"
GMID = 12.566

# 08 第二版尺寸（M1/M2 输入对 W 244.2u；其余见 pvt_sweep.py）
DEVICES = [
    ("M1", "p", 244.2, 0.5), ("M2", "p", 244.2, 0.5),
    ("M3", "n", 3.87, 1.0), ("M4", "n", 3.87, 1.0),
    ("M5", "p", 15.77, 0.5), ("M6", "n", 42.9, 1.0),
    ("M7", "p", 87.43, 0.5), ("M8", "p", 15.77, 0.5),
]


def main() -> int:
    with LUT.open(encoding="utf-8-sig", newline="") as f:
        lut = Lut(list(csv.DictReader(f)))
    print(f"LUT: {LUT.name}   Avt: " + ", ".join(f"{k}={v}mV·µm" for k, v in sorted(lut.avt.items())))
    print(f"{'管':4s}{'dev':4s}{'W(µm)':>8s}{'L(µm)':>7s}{'σ(ΔVt)mV':>10s}{'3σ mV':>8s}{'gm 带(±%)':>11s}")
    for name, dev, w, l in DEVICES:
        sv = sigma_vt_mV(lut, dev, w, l)
        band = band_from_avt(lut, dev, w, l, GMID, 3.0)
        if sv is None or band is None:
            print(f"{name:4s}{dev:4s}{w:8.2f}{l:7.2f}   (缺 avt)")
            continue
        print(f"{name:4s}{dev:4s}{w:8.2f}{l:7.2f}{sv:10.2f}{3 * sv:8.2f}{band['gm_rel'] * 100:11.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())