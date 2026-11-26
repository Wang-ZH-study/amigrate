#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打印 PVT 结果摘要：标称点、每个指标的最坏工况。"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSV = Path(__file__).resolve().parent.parent / "runs" / "2026-11-25-pvt" / "pvt.csv"
KEYS = ("gain", "gbw", "pm", "srp", "srm", "power")
TARGETS = {"gain": 60.0, "gbw": 10.0, "pm": 60.0, "srp": 10.0, "srm": 10.0, "power": 1000.0}


def main() -> int:
    rows = list(csv.DictReader(CSV.open(encoding="utf-8-sig")))
    d = {r["case"]: r for r in rows}
    print(f"总工况：{len(rows)}")
    nom = d.get("pvt_tt_1.0_27")
    if nom:
        print("\n标称 tt/1.8V/27°C：")
        for k in KEYS:
            print(f"  {k:6s} {nom[k]:>10s}  {TARGETS[k]:>8g}")
    print("\n各指标最坏工况：")
    for k in KEYS:
        lo = min(rows, key=lambda r: float(r[k]))
        hi = max(rows, key=lambda r: float(r[k]))
        if k == "power":
            print(f"  {k:6s} 最大 {hi[k]:>10s} @ {hi['case']}")
        else:
            print(f"  {k:6s} 最小 {lo[k]:>10s} @ {lo['case']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())