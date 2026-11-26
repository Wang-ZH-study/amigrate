#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""噪声仿真结果整理：OPA_D 输入参考噪声 vs 单管模型；拟合 1/f 系数 Kf。

用法：python tools/noise_report.py
输出：runs/2026-11-26-noise/README.md
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_noise import parse  # noqa: E402
from solve_lw import Lut  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOISE = ROOT / "runs" / "2026-11-26-noise"
LUT = ROOT / "runs" / "2026-11-25-lut-build" / "13mmrf_io18" / "lut_13mmrf_io18.csv"
K_B = 1.380649e-23
T = 300.0
GAMMA = 2.0 / 3.0
FREQS = (1.0, 10.0, 1e3, 1e4, 1e5, 1e6)


def pick(rows, f):
    return min(rows, key=lambda r: abs(math.log10(r["f"] / f)))


def fit_1f(rows) -> tuple[float, float]:
    """N²(f) = A + B/f 的最小二乘拟合（只用 1e4/1e5/1e6 三个点）。"""
    pts = [pick(rows, f) for f in (1e4, 1e5, 1e6)]
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


def main() -> int:
    opa = parse(NOISE / "opa.nz")
    dev = parse(NOISE / "dev.nz")
    A, B = fit_1f(dev)
    thermal_dev = math.sqrt(A)
    kf = B  # V^2*Hz（在该器件 W=10µm,L=1µm 下）

    # OPA 输入对的“纯热噪声”公式值（只看 M1/M2 沟道热噪声）
    with LUT.open(encoding="utf-8-sig", newline="") as f:
        lut = Lut(list(csv.DictReader(f)))
    sl = None
    gmid_t = 12.566
    best = None
    for vgs_i, g in enumerate(lut.slice_at("p", 0.5, 0.9, 0.0)["gmid"]):
        d = abs(g - gmid_t)
        if best is None or d < best[0]:
            best = (d, vgs_i)
    s = lut.slice_at("p", 0.5, 0.9, 0.0)
    gm10 = s["gm"][best[1]]          # W=10µm 时的 gm
    gm_pair = gm10 * 24.42           # M1/M2 W=244.2µm
    thermal_pair = math.sqrt(2 * 4 * K_B * T * GAMMA / gm_pair)

    lines = [
        "# 噪声仿真结果（2026-11-26）",
        "",
        "## 1. OPA_D v2 输入参考噪声（开环，Vinp 为输入探针）",
        "",
        "| 频率 | 输入参考噪声 | 开环增益 |",
        "|---|---|---|",
    ]
    for f in FREQS:
        p = pick(opa, f)
        lines.append(f"| {p['f']:.3g} Hz | {p['in']*1e9:.2f} nV/√Hz | {p['gain']:.3g} V/V |")
    lines += [
        "",
        "## 2. 单管 n33（W=10µm, L=1µm, Vgs=0.75V, Vds=0.9V）",
        "",
        "| 频率 | 输入参考噪声 | 增益 |",
        "|---|---|---|",
    ]
    for f in FREQS:
        p = pick(dev, f)
        lines.append(f"| {p['f']:.3g} Hz | {p['in']*1e9:.2f} nV/√Hz | {p['gain']:.3g} |")
    lines += [
        "",
        f"拟合：N²(f) = A + B/f，A = {A:.3e} V²/Hz（热噪声底 {thermal_dev*1e9:.2f} nV/√Hz），"
        f"B = {B:.3e} V²·Hz（1/f 系数）。",
        "",
        "## 3. 对比：表格里的公式 vs 仿真",
        "",
        f"- LUT 公式只算沟道热噪声 sqrt(4kTγ/gm)；M1/M2 输入对（W=244.2µm）的公式热噪声 ≈ "
        f"**{thermal_pair*1e9:.2f} nV/√Hz**；",
        f"- 单管仿真热噪声底 ≈ **{thermal_dev*1e9:.2f} nV/√Hz**（比公式高 "
        f"{thermal_dev/thermal_pair:.1f}×，模型含更多噪声源）；",
        f"- OPA 仿真在 10kHz 为 **{pick(opa,1e4)['in']*1e9:.1f} nV/√Hz**、1MHz 为 "
        f"**{pick(opa,1e6)['in']*1e9:.1f} nV/√Hz**，1/f 噪声在低频占主导。",
        "",
        "## 结论",
        "",
        "1. 表格里 inoise 列是**公式推导**，明显低估（未含 1/f 与偏置网络噪声）→ 不能用于噪声预算；",
        "2. 已拿到真实仿真值（OPA 与单管），并拟合出单管 1/f 系数 B；",
        "3. 若要替换表格噪声列：用 N²(f)=4kTγ/gm + Kf/(W·L)/f 形式按面积缩放，Kf 由本实验拟合。",
        "",
    ]
    (NOISE / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\n写入 {NOISE/'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())