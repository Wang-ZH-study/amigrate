#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用实测噪声刷新 LUT 的噪声列（替代纯公式）。

模型（按器件实测校准）：
    inoise²(f) = κ · 4kTγ/gm(行)  +  B_ref · (W_ref·L_ref)/(W·L) / f
其中 κ、B_ref 由单管 noise 仿真拟合：
    n33：W=10µm,L=1µm, Vgs=0.75V, Vds=0.9V
    p33：W=10µm,L=1µm, Vgs=1.05V, Vds=0.9V
W_ref·L_ref = 10·1 µm²；表内归一化宽度 W=10µm，故 1/f 项 = B_ref / L_row。

用法：python tools/add_noise.py --csv runs/.../lut_13mmrf_io18.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_noise import parse  # noqa: E402
from solve_lw import Lut  # noqa: E402

K_B = 1.380649e-23
T = 300.0
GAMMA = 2.0 / 3.0
W_REF_UM, L_REF_UM = 10.0, 1.0
W_NORM = 10.0


def fit_1f(rows) -> tuple[float, float]:
    def pick(f):
        return min(rows, key=lambda r: abs(math.log10(r["f"] / f)))
    pts = [pick(f) for f in (1e4, 1e5, 1e6)]
    xs = [1.0 / p["f"] for p in pts]
    ys = [p["in"] ** 2 for p in pts]
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    B = (n * sxy - sx * sy) / den
    A = (sy - B * sx) / n
    return A, B


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    a = ap.parse_args(argv)
    noise_dir = ROOT / "runs" / "2026-11-26-noise"
    an, bn = fit_1f(parse(noise_dir / "dev.nz"))
    ap_, bp = fit_1f(parse(noise_dir / "dev_p.nz"))

    with a.csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = list(rows[0].keys())
    lut = Lut(rows)

    # 用 LUT 的 gm 计算 κ（实测热噪声底 / 公式热噪声）
    kappa = {}
    for typ, A in (("n", an), ("p", ap_)):
        sl = lut.slice_at(typ, 1.0, 0.9, 0.0)
        vgs_ref = 0.75 if typ == "n" else 1.05
        idx = min(range(len(sl["vgs"])), key=lambda i: abs(sl["vgs"][i] - vgs_ref))
        gm = sl["gm"][idx]  # W=10µm 下的 gm
        formula = 4 * K_B * T * GAMMA / gm
        kappa[typ] = A / formula
    print(f"κ: n={kappa['n']:.3f}, p={kappa['p']:.3f}")

    changed = 0
    for r in rows:
        typ = r["dev"]
        if typ not in kappa:
            continue
        gm = float(r["gm"])
        L = float(r["L"])
        thermal = kappa[typ] * 4 * K_B * T * GAMMA / gm
        flicker_ref = bn if typ == "n" else bp
        flicker = flicker_ref * (W_REF_UM * L_REF_UM) / (W_NORM * L)
        r["inoise_1hz"] = f"{math.sqrt(thermal + flicker):.6g}"
        r["inoise_10k"] = f"{math.sqrt(thermal + flicker / 1e4):.6g}"
        r["noise_src"] = "sim_fit"
        changed += 1
    with a.csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    meta = {
        "date": "2026-11-26",
        "model": "inoise^2(f) = kappa*4kT*gamma/gm + B_ref*(10*1)/(10*L)/f",
        "kappa": {k: round(v, 4) for k, v in kappa.items()},
        "B_ref_V2Hz": {"n": bn, "p": bp},
        "A_thermal_V2Hz": {"n": an, "p": ap_},
        "rows_updated": changed,
        "source": "runs/2026-11-26-noise/dev.nz, dev_p.nz（Spectre noise 仿真拟合）",
    }
    (a.csv.with_name("noise-source.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新 {changed}/{len(rows)} 行噪声列 → {a.csv.with_name('noise-source.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))