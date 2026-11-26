#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""05.7 可行性判定（F0–F4）：OPA_D 8 管能否在 1.8V IO 器件（n33/p33）上成立。

F0 器件存在性：n33/p33 存在（来自 CDF 查询，脚本里硬编码 + 校验表里有 dev）
F1 gm/Id 可达：目标 gm/Id 是否落在某 (L,Vds) 切片的可达区间
F2 W 可实现：总宽能否摊进单指 ≤20 µm、指数 ≤64
F3 电压余量：Vds ≥ Vdsat+50mV，Vgs ≤ 1.8V
F4 带分辨率：Vgs 20mV 步长造成的 gm 误差是否 ≤ 允许带（默认 5%）

用法：
  python tools/feasibility.py --lut runs/2026-11-25-lut-build/13mmrf_io18/lut_13mmrf_io18.csv \
      --out runs/2026-11-25-feasibility-io18
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve_lw import Lut, solve_LW, interp  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SIZING = Path(r"E:\IC-design-first\week_two\02_sizing\sizing_D.csv")
W_FINGER_MAX = 20.0
NF_MAX = 64
VDS_MARGIN_MIN = 0.05
VGS_MAX = 1.8
GM_BAND = 0.05          # 允许的 gm 相对误差（对应迁移规格 5% 容差）
GAIN_RESID_WARN = 0.30  # self_gain 残差超过它 → 增益风险


def load_sizing(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def best_solution(lut: Lut, dev: str, target: dict, vsb: float, source_l: float):
    """在 (L, Vds) 网格上找最优单管解，优先保留源设计 L。"""
    best = None
    f1_reach = False
    gmid_t = target["gm"] / target["id"]
    for vds in lut.vds_values(dev):
        cands = solve_LW(lut, dev, target, vds, vsb)
        for c in cands:
            L = c["L_um"]
            sl = lut.slice_at(dev, L, vds, vsb)
            if sl is None:
                continue
            lo, hi = min(sl["gmid"]), max(sl["gmid"])
            if not (lo - 1e-9 <= gmid_t <= hi + 1e-9):
                continue
            f1_reach = True
            score = (abs(L - source_l), c["residual"], abs(vds - 0.9))
            if best is None or score < best[0]:
                best = (score, L, vds, c, sl)
    return best, f1_reach


def evaluate(lut: Lut, d: dict) -> dict:
    dev = d["type"]
    id_t = float(d["Id_uA"]) * 1e-6
    gmid = float(d["gmid"])
    sg = 10 ** (float(d["Aint_dB"]) / 20)
    target = {"id": id_t, "gm": gmid * id_t, "self_gain": sg}
    vsb = float(d["Vsb"])
    src_l = float(d["L_um"])

    # F0：表里有该器件
    f0 = dev in ("n", "p") and bool(lut.L_values(dev))

    best, f1_reach = best_solution(lut, dev, target, vsb, src_l)
    if best is None:
        return {"name": d["name"], "dev": dev, "f0": f0, "f1": f1_reach,
                "verdict": "不可行", "reason": "F1：目标 gm/Id 在 IO 表任意 (L,Vds) 都不可达"}
    _, L, vds, c, sl = best
    w_total = c["W_um"]
    nf = max(1, math.ceil(w_total / W_FINGER_MAX))
    f2 = nf <= NF_MAX and (w_total / nf) <= W_FINGER_MAX + 1e-9
    vdsat = interp(sl["vgs"], sl["vdsat"], c["Vgs"]) or 0.0
    margin = vds - vdsat
    f3 = margin >= VDS_MARGIN_MIN and c["Vgs"] <= VGS_MAX + 1e-9
    h = sl["vgs"][1] - sl["vgs"][0] if len(sl["vgs"]) > 1 else 0.02
    gm0 = interp(sl["vgs"], sl["gm"], c["Vgs"])
    gm_lo = interp(sl["vgs"], sl["gm"], c["Vgs"] - h)
    gm_hi = interp(sl["vgs"], sl["gm"], c["Vgs"] + h)
    if gm0 and gm_lo and gm_hi:
        # 二阶差分估计线性插值误差：err ≈ |gm''| h² / 8 / gm ≈ |Δ²gm| / (8·gm)
        gm_err = abs(gm_hi - 2 * gm0 + gm_lo) / (8 * gm0)
    else:
        gm_err = float("nan")
    f4 = (not math.isnan(gm_err)) and gm_err <= GM_BAND
    gain_risk = c["residual"] > GAIN_RESID_WARN

    hard_fail = (not f0) or (not f1_reach) or (not f3)
    soft_issue = (not f2) or (not f4) or gain_risk or abs(L - src_l) > 1e-6
    verdict = "不可行" if hard_fail else ("有条件可行" if soft_issue else "可行")

    reasons = []
    if not f1_reach:
        reasons.append("F1 不可达")
    if not f2:
        reasons.append(f"F2 需 nf>{NF_MAX}")
    if not f3:
        reasons.append(f"F3 余量 {margin*1e3:.0f}mV/Vgs {c['Vgs']:.2f}V")
    if not f4:
        reasons.append(f"F4 分辨率 {gm_err*100:.1f}%")
    if gain_risk:
        reasons.append(f"增益风险 residual={c['residual']:.2f}")
    if abs(L - src_l) > 1e-6:
        reasons.append(f"改 L {src_l}→{L}")
    return {
        "name": d["name"], "dev": dev, "id_uA": id_t * 1e6, "gmid_target": gmid,
        "L_um": L, "W_um": round(w_total, 3), "nf": nf, "Vgs": round(c["Vgs"], 4),
        "Vds": vds, "vdsat": round(vdsat, 4), "margin_mV": round(margin * 1e3, 1),
        "self_gain_solved": round(c["self_gain"], 1), "self_gain_target": round(sg, 1),
        "residual": round(c["residual"], 4), "gm_step_err": round(gm_err * 100, 2) if not math.isnan(gm_err) else "",
        "f0": f0, "f1": f1_reach, "f2": f2, "f3": f3, "f4": f4,
        "gain_risk": gain_risk, "verdict": verdict, "reason": "; ".join(reasons),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="05.7 可行性判定 F0–F4")
    ap.add_argument("--lut", type=Path, required=True)
    ap.add_argument("--sizing", type=Path, default=SIZING)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "2026-11-25-feasibility-io18")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)

    with a.lut.open(encoding="utf-8-sig", newline="") as f:
        lut = Lut(list(csv.DictReader(f)))
    rows = [evaluate(lut, d) for d in load_sizing(a.sizing)]

    csv_path = a.out / "feasibility.csv"
    keys = sorted({k for r in rows for k in r})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["verdict"] == "可行"]
    cond = [r for r in rows if r["verdict"] == "有条件可行"]
    bad = [r for r in rows if r["verdict"] == "不可行"]
    print("=" * 96)
    print(f"05.7 可行性：可行 {len(ok)} / 有条件 {len(cond)} / 不可行 {len(bad)}（共 {len(rows)}）")
    print("=" * 96)
    print(f"{'管':4s}{'dev':4s}{'L':>6s}{'W(µm)':>8s}{'nf':>4s}{'Vgs':>7s}{'Vds':>5s}"
          f"{'余量mV':>7s}{'残差':>7s}{'F4误差':>7s}  {'判定':8s} 原因")
    for r in rows:
        print(f"{r['name']:4s}{r['dev']:4s}{r.get('L_um',0):6.2f}{r.get('W_um',0):8.2f}"
              f"{r.get('nf',0):4d}{r.get('Vgs',0):7.3f}{r.get('Vds',0):5.1f}"
              f"{r.get('margin_mV',0):7.0f}{r.get('residual',0):7.3f}"
              f"{str(r.get('gm_step_err','')):>7s}  {r['verdict']:8s} {r.get('reason','')}")

    lines = ["# 05.7 可行性判定（1.8V，n33/p33 IO 器件）", "",
             f"- 日期：2026-11-25", f"- 表：`{a.lut}`",
             f"- 判据：F0 器件存在；F1 gm/Id 可达；F2 nf≤{NF_MAX} 且单指≤{W_FINGER_MAX}µm；"
             f"F3 Vds≥Vdsat+{VDS_MARGIN_MIN*1e3:.0f}mV 且 Vgs≤{VGS_MAX}V；F4 Vgs 步长 gm 误差≤{GM_BAND:.0%}",
             f"- 增益风险阈值：self_gain 残差 > {GAIN_RESID_WARN}", "",
             f"**总判：可行 {len(ok)} / 有条件 {len(cond)} / 不可行 {len(bad)}**", "",
             "| 管 | dev | L (µm) | W (µm) | nf | Vgs | Vds | 余量 mV | 残差 | F4 | 判定 | 原因 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['dev']} | {r.get('L_um', '')} | {r.get('W_um', '')} | "
                     f"{r.get('nf', '')} | {r.get('Vgs', '')} | {r.get('Vds', '')} | "
                     f"{r.get('margin_mV', '')} | {r.get('residual', '')} | {r.get('gm_step_err', '')} | "
                     f"{r['verdict']} | {r.get('reason', '')} |")
    lines += ["", "## 说明", "",
              "- 这是**单管级**判定：同一支路多管由 KCL 耦合，结论只回答“目标工作点能不能实现”；",
              "- 残差大（>0.3）表示同 L 下 self_gain 与源设计差得多，08 重定尺寸必须改 L 或调偏置；",
              "- F4 用 Vgs ±10mV 的 gm 变化近似表分辨率误差，与 5% 容差比较；",
              "- 噪声/失配列仍是推导值，不参与本判定。", ""]
    (a.out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n结果：{csv_path}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))