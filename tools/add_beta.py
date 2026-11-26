#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 13mmrf 模型失配参数提取电流增益 β 的失配上下限（β0/β1），写入 LUT。

β ∝ µ·Cox·W/L，相对失配近似：
    σ²(Δβ/β) ≈ (du0)² + (dtox/tox)² + (dxl/L)²
其中（W、L 用 µm，模型参数取自 ms013_io33_v2p6_7p_spe.lib）：
    du0 = au0 / √(W·L)
    dtox/tox = (atox / √(W·L)) / tox
    dxl/L = (axl / √W) / L
结果：beta0_low/high = 1 ∓ 3σ，beta1_low/high 同（当前两者都用同一 3σ 带）。

用法：python tools/add_beta.py --csv runs/.../lut_13mmrf_io18.csv
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

# PDK 参数（V·µm / m·µm 等，见 lib 内 parameters 定义）
PARAMS = {
    "n": {"au0": 6e-4, "atox": 4e-11, "axl": 3e-9, "tox": 7e-9},
    "p": {"au0": 6e-4, "atox": 2.85e-11, "axl": 8e-10, "tox": 7e-9},
}


def sigma_beta(typ: str, w_um: float, l_um: float) -> float:
    p = PARAMS[typ]
    wl = max(w_um * l_um, 1e-12)
    du0 = p["au0"] / math.sqrt(wl)
    dtox = p["atox"] / math.sqrt(wl) / p["tox"]
    dxl = p["axl"] / math.sqrt(max(w_um, 1e-12)) / (l_um * 1e-6)
    return math.sqrt(du0 ** 2 + dtox ** 2 + dxl ** 2)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    a = ap.parse_args(argv)
    with a.csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("空表")
        return 1
    keys = list(rows[0].keys())
    n_changed = 0
    for r in rows:
        typ = r["dev"]
        if typ not in PARAMS:
            continue
        sg = sigma_beta(typ, float(r["W"]), float(r["L"]))
        lo, hi = 1 - 3 * sg, 1 + 3 * sg
        r["beta0_low"] = f"{lo:.5f}"
        r["beta0_high"] = f"{hi:.5f}"
        r["beta1_low"] = f"{lo:.5f}"
        r["beta1_high"] = f"{hi:.5f}"
        n_changed += 1
    with a.csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    # 汇总每个器件在若干 (W,L) 下的 σβ
    summary = {}
    for typ in PARAMS:
        samples = []
        for w, l in ((10.0, 1.0), (100.0, 0.5), (1.0, 1.0)):
            sg = sigma_beta(typ, w, l)
            samples.append({"W_um": w, "L_um": l, "sigma_beta": round(sg, 6),
                            "3sigma_pct": round(3 * sg * 100, 3)})
        summary[typ] = samples
    meta = {
        "date": "2026-11-26",
        "formula": "sigma^2(dbeta/beta) = du0^2 + (dtox/tox)^2 + (dxl/L)^2",
        "params": PARAMS,
        "summary": summary,
        "rows_updated": n_changed,
    }
    (a.csv.with_name("beta-source.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新 {n_changed}/{len(rows)} 行 beta 列")
    for typ, samples in summary.items():
        print(f"  {typ}: " + ", ".join(f"W{s['W_um']:g}/L{s['L_um']:g}: {s['3sigma_pct']:.2f}%"
                                       for s in samples))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))