#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 13mmrf 迁移版 LUT 给 OPA_D 的 8 个管子求候选 (L, W)（05.5 的首次实战）。

输入：runs/2026-11-25-lut-build/13mmrf/lut_13mmrf.csv + 上游 sizing_D.csv
输出：runs/2026-11-25-solve-13mmrf/{sizing_solution.csv, README.md}

注意：这是**逐管解**，不是电路级解——同一支路多管电流由 KCL 耦合，
必须再把候选尺寸喂给电路 DC 迭代（07/08）才能定稿。CSV 里 W 是"总宽"，
进原理图前还要按目标 PDK 的 CDF 规则摊成 nf/m（见 docs/porting/lut-to-schematic-pipeline.md）。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve_lw import Lut, solve_LW  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LUT = ROOT / "runs" / "2026-11-25-lut-build" / "13mmrf" / "lut_13mmrf.csv"
SIZING = Path(r"E:\IC-design-first\week_two\02_sizing\sizing_D.csv")
OUT = ROOT / "runs" / "2026-11-25-solve-13mmrf"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="用目标 PDK 的迁移版 LUT 给 OPA_D 8 管求候选尺寸")
    ap.add_argument("--lut", type=Path, default=LUT)
    ap.add_argument("--sizing", type=Path, default=SIZING)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    lut_path, sizing_path, out_dir = a.lut, a.sizing, a.out
    lut = Lut(list(csv.DictReader(lut_path.open(encoding="utf-8-sig"))))
    sizing = list(csv.DictReader(sizing_path.open(encoding="utf-8-sig")))
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for d in sizing:
        id_t = float(d["Id_uA"]) * 1e-6
        gmid = float(d["gmid"])
        sg = 10 ** (float(d["Aint_dB"]) / 20)
        best = None
        for vds in lut.vds_values(d["type"]):
            cands = solve_LW(lut, d["type"], {"id": id_t, "gm": gmid * id_t, "self_gain": sg},
                             vds, float(d["Vsb"]))
            if not cands:
                continue
            target_l = float(d["L_um"])
            cand = min(cands, key=lambda x: abs(x["L_um"] - target_l))
            if best is None or cand["residual"] < best[1]["residual"]:
                best = (vds, cand)
        if not best:
            rows.append({"name": d["name"], "type": d["type"], "status": "no_candidate"})
            continue
        vds, c = best
        rows.append({
            "name": d["name"], "type": d["type"],
            "Id_uA": float(d["Id_uA"]), "gmoverid_target": gmid,
            "Aint_dB": float(d["Aint_dB"]), "Vsb": float(d["Vsb"]),
            "L_um": round(c["L_um"], 3), "W_um_total": round(c["W_um"], 3),
            "Vgs_solved": round(c["Vgs"], 4), "Vds_assumed": vds,
            "self_gain_solved": round(c["self_gain"], 1), "residual": round(c["residual"], 5),
            "status": "candidate",
        })

    csv_path = out_dir / "sizing_solution.csv"
    keys = sorted({k for r in rows for k in r})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    print(f"{'管':4s} {'类型':3s} {'L(µm)':>6s} {'W(µm)':>8s} {'Vgs(V)':>7s} {'Vds':>5s} {'残差':>7s}")
    for r in rows:
        if r.get("status") == "no_candidate":
            print(f"{r['name']:4s} 无候选")
            continue
        print(f"{r['name']:4s} {r['type']:3s} {r['L_um']:6.2f} {r['W_um_total']:8.2f} "
              f"{r['Vgs_solved']:7.3f} {r['Vds_assumed']:5.1f} {r['residual']:7.4f}")

    lines = [
        "# 13mmrf 逐管候选尺寸（首战）",
        "",
        "> 由 `tools/solve_sizing_13mmrf.py` 生成。**逐管解，不是电路级解**；W 是总宽。",
        "",
        "| 管 | 类型 | Id (µA) | gm/Id | L (µm) | W 总宽 (µm) | Vgs (V) | 假定 Vds | 残差 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("status") == "no_candidate":
            lines.append(f"| {r['name']} | {r['type']} | - | - | - | - | - | - | 无候选 |")
        else:
            lines.append(f"| {r['name']} | {r['type']} | {r['Id_uA']:.1f} | {r['gmoverid_target']:.2f} | "
                         f"{r['L_um']:.2f} | {r['W_um_total']:.2f} | {r['Vgs_solved']:.3f} | "
                         f"{r['Vds_assumed']:.1f} | {r['residual']:.4f} |")
    lines += [
        "",
        "## 怎么用",
        "",
        "1. 这些 (L, W) 只是**起点**；同一支路多管由 KCL 耦合，需进电路级 DC 迭代（07/08）；",
        "2. 进原理图前要把总宽 W 按目标 PDK CDF 摊成 `nf`/`m` 与单指宽（05.2 定规则）；",
        "3. core/IO 档位未定，本表默认用 n12/p12（1.2V core），若改 1.8V IO 器件需重解。",
        "",
        "## 已知限制",
        "",
        "- Vds 是用 self_gain 反推的，不是源电路实测 Vds；",
        "- 13mmrf 表里 avt=0（pending），所以容忍带判据未启用；",
        "- 噪声列是推导值，本表不参与噪声判断。",
    ]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n写入 {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())