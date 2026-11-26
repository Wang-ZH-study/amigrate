#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""05.6 自洽性回归：用上游 gmid_table.csv 反解上游 sizing_D.csv 的 8 个管子。

目的：在**不依赖目标 PDK** 的前提下，回答"这套 LUT + 反解器在自己的数据上收不收敛"。

方法：
  1. 目标取自 sizing_D.csv：Id、gm/Id、Aint(dB)、Vsb、L；
  2. 目标 gm = (gm/Id)·Id；目标 self_gain = 10^(Aint/20)；
  3. 对目标表里每个 Vds 切片跑 solve_LW，取 self_gain 残差最小的候选
     —— **选 Vds 时不用原 W**（否则就是循环论证），原 W 只用于事后对比；
  4. 比较解得 W 与原 W（±5% 算通过）；
  5. 输出分辨率评估：同一管在不同 Vds 切片下解得的 W 散布（Vds 歧义）、候选 L 数。

已知边界（必须写进报告）：
  - 上游表只有饱和行（region==2），所以本回归只验证饱和区；
  - 表里没有逐管 Vds，用 self_gain 选 Vds 是**推断**，不是实测；
  - SPICE 抽检需要 Virtuoso/Spectre 环境，本轮未做（见工单 05.2 的前置）。

用法：
  python tools/lut_selfcheck.py
  python tools/lut_selfcheck.py --lut <csv> --sizing <csv> --out runs/<date>-lut-selfcheck
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve_lw import Lut, solve_LW  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_LUT = Path(r"E:\IC-design-first\exchange\gmid\gmid_table.csv")
DEFAULT_SIZING = Path(r"E:\IC-design-first\week_two\02_sizing\sizing_D.csv")


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="05.6 自洽性回归")
    ap.add_argument("--lut", type=Path, default=DEFAULT_LUT)
    ap.add_argument("--sizing", type=Path, default=DEFAULT_SIZING)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "2026-11-25-lut-selfcheck")
    ap.add_argument("--tol", type=float, default=0.05, help="W 相对误差容忍")
    a = ap.parse_args(argv)

    if not a.lut.exists() or not a.sizing.exists():
        print(f"输入不存在：lut={a.lut} sizing={a.sizing}")
        return 2

    lut = Lut(load_csv(a.lut))
    sizing = load_csv(a.sizing)
    a.out.mkdir(parents=True, exist_ok=True)

    rows_out = []
    passed = 0
    for dev in sizing:
        name = dev["name"]
        typ = dev["type"]
        L_um = float(dev["L_um"])
        W_true = float(dev["W_um"])
        id_t = float(dev["Id_uA"]) * 1e-6
        gmid = float(dev["gmid"])
        vsb = float(dev["Vsb"])
        sg_t = 10 ** (float(dev["Aint_dB"]) / 20.0)
        gm_t = gmid * id_t

        per_vds = []
        for vds in lut.vds_values(typ):
            cands = solve_LW(lut, typ, {"id": id_t, "gm": gm_t, "self_gain": sg_t}, vds, vsb)
            if not cands:
                continue
            # 只保留 L 与设计值一致的候选（设计已知 L）
            same_l = [c for c in cands if abs(c["L_um"] - L_um) < 1e-3]
            pick = same_l[0] if same_l else cands[0]
            per_vds.append((vds, pick, len(cands), len(same_l)))

        if not per_vds:
            rows_out.append({"name": name, "type": typ, "status": "no_candidate"})
            continue

        vds_best, best, n_cand, n_same = min(per_vds, key=lambda t: t[1]["residual"])
        w_err = abs(best["W_um"] - W_true) / W_true
        ok = w_err <= a.tol and n_same > 0
        passed += int(ok)
        w_spread = (max(t[1]["W_um"] for t in per_vds) - min(t[1]["W_um"] for t in per_vds)) \
            / max(t[1]["W_um"] for t in per_vds) * 100
        rows_out.append({
            "name": name, "type": typ, "L_um": L_um, "W_true_um": W_true,
            "Id_uA": id_t * 1e6, "gmid": gmid, "Aint_dB": float(dev["Aint_dB"]),
            "Vsb": vsb, "Vds_pick": vds_best, "Vgs_solved": round(best["Vgs"], 4),
            "W_solved_um": round(best["W_um"], 4), "W_err_pct": round(w_err * 100, 2),
            "self_gain_solved": round(best["self_gain"], 2), "self_gain_target": round(sg_t, 2),
            "residual": round(best["residual"], 5), "n_candidates": n_cand,
            "n_same_L": n_same, "W_spread_across_vds_pct": round(w_spread, 2),
            "status": "pass" if ok else "fail",
        })

    # 写结果 CSV
    csv_path = a.out / "results.csv"
    if rows_out:
        keys = sorted({k for r in rows_out for k in r})
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in rows_out:
                w.writerow(r)

    n = len(sizing)
    ok_rows = [r for r in rows_out if r.get("status") == "pass"]
    failed = [r for r in rows_out if r.get("status") != "pass"]

    print("=" * 72)
    print(f"05.6 自洽性回归：{n} 个管子，通过 {len(ok_rows)}（W 误差 ≤ {a.tol:.0%}）")
    print("=" * 72)
    print(f"{'管':4s} {'类型':3s} {'L':>5s} {'W真值':>8s} {'W解':>8s} {'误差%':>7s} "
          f"{'Vds':>5s} {'残留':>7s}")
    for r in rows_out:
        if r.get("status") == "no_candidate":
            print(f"{r['name']:4s} {r.get('type', ''):3s}  无候选")
            continue
        print(f"{r['name']:4s} {r['type']:3s} {r['L_um']:5.2f} {r['W_true_um']:8.2f} "
              f"{r['W_solved_um']:8.2f} {r['W_err_pct']:7.2f} {r['Vds_pick']:5.1f} {r['residual']:7.4f}")

    # 简单分辨率评估：Vds 歧义与候选数
    if ok_rows:
        spread = sum(r["W_spread_across_vds_pct"] for r in ok_rows) / len(ok_rows)
        print(f"\n分辨率评估：通过样本在不同 Vds 切片下解得 W 的平均散布 {spread:.1f}%"
              f"（越小说明 Vds 歧义影响越小）")
    print(f"\n结果：{csv_path}")

    # README
    lines = [
        "# 05.6 自洽性回归结果",
        "",
        f"- 日期：2026-11-25",
        f"- 输入表：`{a.lut}`（上游 gm/Id 表，{len(lut.slices)} 个切片，仅饱和行）",
        f"- 设计输入：`{a.sizing}`（8 管，L=0.5 µm）",
        f"- 判据：解得 W 与原 W 相对误差 ≤ {a.tol:.0%}，且 L 与设计一致",
        "",
        "## 结果",
        "",
        "| 管 | 类型 | W 真值 (µm) | W 反解 (µm) | 误差 | 选定 Vds (V) | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows_out:
        if r.get("status") == "no_candidate":
            lines.append(f"| {r['name']} | {r.get('type', '')} | - | - | - | - | 无候选 |")
        else:
            lines.append(f"| {r['name']} | {r['type']} | {r['W_true_um']:.3f} | "
                         f"{r['W_solved_um']:.3f} | {r['W_err_pct']:.2f}% | {r['Vds_pick']:.1f} | "
                         f"{'✅' if r['status'] == 'pass' else '❌'} |")
    lines += [
        "",
        f"**通过 {len(ok_rows)}/{n}**。",
        "",
        "## 方法",
        "",
        "1. 目标取自 sizing_D.csv 的 (Id, gm/Id, Aint, Vsb, L)；",
        "2. gm = (gm/Id)·Id，self_gain = 10^(Aint/20)；",
        "3. 对每个 Vds 切片反解，取 self_gain 残差最小的候选——**选 Vds 不看原 W**，避免循环论证；",
        "4. 原 W 只用于事后对比。",
        "",
        "## 已知边界",
        "",
        "- 上游表只有饱和行（region==2），本回归只覆盖饱和区；",
        "- 表里没有逐管 Vds，用 self_gain 反推 Vds 是推断而非实测；",
        "- SPICE 抽检（2 管）需要 Virtuoso/Spectre 环境，本轮未做，待 05.2 的 VM 前置完成后补；",
        "- 本表是**设计用**表（缺噪声/失配列），迁移版表的完整校验见 `tools/check_lut.py`。",
    ]
    (a.out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 0 if len(ok_rows) >= 6 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))