#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 PDK 失配参数（Pelgrom Avt）写进迁移版 LUT 的 avt 列。

与华为 CN116964587A 的容忍带定义保持一致：
    σ(ΔVt) = Avt / √(W·L)      （W、L 单位 µm，Avt 单位 mV·µm）
    容忍带：gm_target ∈ [gm_org, gm_org + 3σ]（3σ）
其中 avt 直接取 PDK 模型参数（13mmrf IO lib）：
    atox_n33/avth_n33 = 9.5e-3 V·µm   → 9.5 mV·µm
    avth_p33         = 3.5e-3 V·µm   → 3.5 mV·µm

用法：
  python tools/add_avt.py --csv runs/2026-11-25-lut-build/13mmrf_io18/lut_13mmrf_io18.csv \
      --avt n=9.5 --avt p=3.5
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--avt", action="append", default=[],
                    help="dev=Avt(mV·um)，例如 n=9.5")
    a = ap.parse_args(argv)
    avt_map = {}
    for item in a.avt:
        k, v = item.split("=", 1)
        avt_map[k.strip()] = float(v)
    if not avt_map:
        print("需要 --avt n=.. p=..")
        return 2

    with a.csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("空表")
        return 1
    keys = list(rows[0].keys())
    n_changed = 0
    for r in rows:
        dev = r["dev"]
        if dev in avt_map:
            r["avt"] = f"{avt_map[dev]:g}"
            r["avt_src"] = "model"
            n_changed += 1
    with a.csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    src = {
        "date": "2026-11-26",
        "pdk": "PDK_13mmrf_1P6M_30k",
        "model_file": "models/spectre/ms013_io33_v2p6_7p_spe.lib",
        "parameter": {"n": "avth_n33 = 9.5e-3 V*um", "p": "avth_p33 = 3.5e-3 V*um"},
        "formula": "sigma(dVt) = Avt / sqrt(W*L), W/L in um; band gm in [gm_org, gm_org+3sigma]",
        "avt_mVum": avt_map,
        "rows_updated": n_changed,
    }
    meta = a.csv.with_name("avt-source.json")
    meta.write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新 {n_changed}/{len(rows)} 行；avt 来源写入 {meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))