#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比两个 Spectre 网表（原理图导出 vs 手写参考）：端口、器件、连接、尺寸。

用法：python tools/netlist_diff.py --a runs/.../opa_d_export.scs --b runs/.../pvt_tt_1.0_27_ac.scs
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEV = re.compile(r'^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(\S+)(.*)$')
SUB = re.compile(r'^\s*subckt\s+(\w+)\s+(.*)$')
PQ = re.compile(r'(\w+)=([^\s]+)')
MOS_MODELS = ("n33", "p33", "n12", "p12", "n18e2r", "p18e2r")


def parse(path: Path) -> dict:
    """返回 {'ports': [...], 'devs': {name: {'terms':[...], 'model':..., 'w':..., 'l':...}}}"""
    out = {"ports": [], "devs": {}}
    in_sub = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        t = line.strip()
        if t.startswith("//") or not t:
            continue
        m = SUB.match(t)
        if m:
            out["name"] = m.group(1)
            out["ports"] = m.group(2).split()
            in_sub = True
            continue
        if t.startswith("ends"):
            in_sub = False
            continue
        if not in_sub:
            continue
        m = DEV.match(t)
        if not m:
            continue
        name, terms, model, rest = m.group(1), m.group(2).split(), m.group(3), m.group(4)
        params = {k: v for k, v in PQ.findall(rest)}
        out["devs"][name] = {"terms": terms, "model": model, "params": params}
    return out


def norm_terms(dev: dict) -> list[str]:
    terms = dev["terms"]
    if dev["model"] in MOS_MODELS and len(terms) == 4:
        return terms  # D G S B 顺序已统一
    return sorted(terms)  # 无源器件端子与顺序无关


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True, help="原理图导出网表")
    ap.add_argument("--b", type=Path, required=True, help="参考/手写网表")
    a = ap.parse_args(argv)
    na, nb = parse(a.a), parse(a.b)
    diffs = []

    if set(na["ports"]) != set(nb["ports"]):
        diffs.append(f"端口集合不同：导出={sorted(na['ports'])} / 参考={sorted(nb['ports'])}")

    da, db = na["devs"], nb["devs"]
    only_a = sorted(set(da) - set(db))
    only_b = sorted(set(db) - set(da))
    if only_a:
        diffs.append(f"仅导出有：{only_a}")
    if only_b:
        diffs.append(f"仅参考有：{only_b}")

    for name in sorted(set(da) & set(db)):
        A, B = da[name], db[name]
        if A["model"] != B["model"]:
            diffs.append(f"{name}: 器件类型 {A['model']} vs {B['model']}")
        ta, tb = norm_terms(A), norm_terms(B)
        if ta != tb:
            diffs.append(f"{name}: 连接 {ta} vs {tb}")
        for key in ("w", "l"):
            va = A["params"].get(key, "").rstrip("uUmM")
            vb = B["params"].get(key, "").rstrip("uUmM")
            if va and vb:
                try:
                    if abs(float(va) - float(vb)) > 1e-3:
                        diffs.append(f"{name}.{key}: {A['params'].get(key)} vs {B['params'].get(key)}")
                except ValueError:
                    pass

    print(f"对比：A={a.a.name}  B={a.b.name}")
    print(f"器件数：A={len(da)}  B={len(db)}")
    if diffs:
        print(f"\n发现 {len(diffs)} 处差异：")
        for d in diffs:
            print(f"  - {d}")
        return 1
    print("\n结论：端口、器件、连接、MOS 尺寸一致 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))