#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析 psfascii AC 结果：开环增益、单位增益频率、相位裕度。

用法：python tools/parse_ac_gain.py runs/2026-11-25-io18-ac/src.ac runs/2026-11-25-io18-ac/tgt.ac
"""
from __future__ import annotations

import cmath
import math
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FREQ = re.compile(r'^"freq"\s+([-\d.eE+]+)')
VAL = re.compile(r'^"([^"]+)"\s+\(([-\d.eE+]+)\s+([-\d.eE+]+)\)')


def read_ac(path: Path) -> dict[str, list[tuple[float, complex]]]:
    data: dict[str, list[tuple[float, complex]]] = {}
    f = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = FREQ.match(line)
        if m:
            f = float(m.group(1))
            continue
        m = VAL.match(line)
        if m and f is not None:
            name = m.group(1)
            if name == "freq":
                continue
            data.setdefault(name, []).append((f, complex(float(m.group(2)), float(m.group(3)))))
    return data


def summarize(path: Path) -> dict:
    d = read_ac(path)
    out = d.get("OUT", [])
    if not out:
        return {"path": path, "ok": False}
    gain_db = {f: 20 * math.log10(abs(v)) for f, v in out if abs(v) > 0}
    f0 = out[0][0]
    g0 = gain_db[f0]
    # 单位增益频率：|H| 穿越 0dB（线性插值，dB 域）
    ugf = None
    pm = None
    rows = sorted(gain_db.items())
    for (f1, g1), (f2, g2) in zip(rows, rows[1:]):
        if g1 > 0 >= g2:
            t = g1 / (g1 - g2) if g1 != g2 else 0
            ugf = 10 ** (math.log10(f1) + t * (math.log10(f2) - math.log10(f1)))
            # 相位：OUT 相对 VINP 的相角
            ang1 = cmath.phase(dict(out)[f1]) * 180 / math.pi
            ang2 = cmath.phase(dict(out)[f2]) * 180 / math.pi
            ang = ang1 + t * (ang2 - ang1)
            pm = 180 + ang if ang < 0 else 180 - ang
            break
    return {"path": path, "ok": True, "gain_db_1hz": g0, "ugf_hz": ugf, "pm_deg": pm,
            "nfreq": len(out), "last_freq": out[-1][0],
            "gain_db_last": gain_db[out[-1][0]]}


def main(argv: list[str]) -> int:
    print(f"{'文件':<38}{'DC增益(dB)':>12}{'UGF(Hz)':>14}{'PM(°)':>10}")
    for arg in argv:
        s = summarize(Path(arg))
        if not s["ok"]:
            print(f"{Path(arg).name:<38}{'无 OUT 数据':>12}")
            continue
        ugf = f"{s['ugf_hz']:.3g}" if s["ugf_hz"] else "未穿越"
        pm = f"{s['pm_deg']:.1f}" if s["pm_deg"] is not None else "-"
        print(f"{Path(arg).name:<38}{s['gain_db_1hz']:12.2f}{ugf:>14}{pm:>10}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))