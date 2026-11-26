#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析 Spectre noise 结果：输入参考噪声 IRN（V/√Hz）与增益。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FREQ = re.compile(r'^"freq"\s+([-\d.eE+]+)\s*$')
SCAL = re.compile(r'^"(in|out|gain)"\s+([-\d.eE+]+)\s*$')
TARGETS = (1.0, 10.0, 1e3, 1e4, 1e5, 1e6)


def parse(path: Path):
    rows, cur = [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = FREQ.match(line)
        if m:
            cur = {"f": float(m.group(1))}
            continue
        m = SCAL.match(line)
        if m and cur is not None:
            cur[m.group(1)] = float(m.group(2))
            if "in" in cur and "out" in cur and "gain" in cur:
                rows.append(cur)
                cur = None
    return rows


def main(argv):
    for arg in argv:
        p = Path(arg)
        rows = parse(p)
        print(f"=== {p.name}（{len(rows)} 频点）")
        print(f"{'freq':>10s}{'IRN(V/√Hz)':>14s}{'IRN(nV/√Hz)':>14s}{'gain(V/V)':>12s}")
        for f in TARGETS:
            best = min(rows, key=lambda r: abs(r["f"] / f - 1)) if rows else None
            if best and abs(best["f"] / f - 1) < 0.3:
                print(f"{best['f']:10.3g}{best['in']:14.3e}{best['in']*1e9:14.2f}{best['gain']:12.3g}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))