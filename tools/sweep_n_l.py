#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""08 预研：n 管（M3/M4/M6）L 扫描，重解 W 并生成对应 AC 网表。

L ∈ {0.5, 0.7, 1.0, 1.5} µm（n33 的 lmin=0.35，均合法）；p 管保持 0.5µm 的解。
输出：runs/2026-11-25-io18-ac/sweep/tgt_L{0p5,0p7,1p0,1p5}.scs 与 sizes.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve_lw import Lut, solve_LW  # noqa: E402
from make_io18_testbench import TOPO, netlist, INCLUDE_TGT  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LUT = ROOT / "runs" / "2026-11-25-lut-build" / "13mmrf_io18" / "lut_13mmrf_io18.csv"
SIZING = Path(r"E:\IC-design-first\week_two\02_sizing\sizing_D.csv")
OUT = ROOT / "runs" / "2026-11-25-io18-ac" / "sweep"
L_LIST = [0.5, 0.7, 1.0, 1.5]
N_DEVS = ["M3", "M4", "M6"]          # 只扫 n 管
P_FIX = {                            # p 管沿用 1.8V 0.5µm 候选（feasibility 结果）
    "M1": ("p", "7.63u"),
    "M2": ("p", "7.63u"),
    "M5": ("p", "15.77u"),
    "M7": ("p", "87.43u"),
    "M8": ("p", "15.77u"),
}


def solve_at_l(lut: Lut, d: dict, L_target: float):
    id_t = float(d["Id_uA"]) * 1e-6
    gmid = float(d["gmid"])
    sg = 10 ** (float(d["Aint_dB"]) / 20)
    cands = solve_LW(lut, d["type"], {"id": id_t, "gm": gmid * id_t, "self_gain": sg},
                     0.9, float(d["Vsb"]))
    if not cands:
        return None
    best = min(cands, key=lambda c: (abs(c["L_um"] - L_target), c["residual"]))
    return best


def main() -> int:
    with LUT.open(encoding="utf-8-sig", newline="") as f:
        lut = Lut(list(csv.DictReader(f)))
    sizing = {d["name"]: d for d in csv.DictReader(SIZING.open(encoding="utf-8-sig"))}
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for L in L_LIST:
        devs = {}
        for name in ("M1", "M2", "M5", "M7", "M8"):
            typ, w = P_FIX[name]
            devs[name] = (typ, w, "0.5u", 1)
        for name in N_DEVS:
            c = solve_at_l(lut, sizing[name], L)
            if c is None:
                print(f"L={L} {name} 无解")
                return 1
            w = f"{c['W_um']:.3g}u"
            devs[name] = ("n", w, f"{L:g}u", 1)
            rows.append({"L": L, "name": name, "W_um": round(c["W_um"], 3),
                         "Vgs": round(c["Vgs"], 4), "residual": round(c["residual"], 4)})
        tag = f"L{L:g}".replace(".", "p")
        path = OUT / f"tgt_{tag}.scs"
        path.write_text(netlist(devs, INCLUDE_TGT, "n33", "p33",
                                f"OPA_D target n33/p33, n-L={L:g}um"),
                        encoding="utf-8", newline="\n")
        print(f"[{tag}] 写入 {path}  n 管尺寸: " +
              ", ".join(f"{n}={devs[n][1]}" for n in N_DEVS))
    with (OUT / "sizes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["L", "name", "W_um", "Vgs", "residual"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n尺寸表：{OUT/'sizes.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())