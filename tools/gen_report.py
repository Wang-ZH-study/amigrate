#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 runs/ 结果生成验证报告 Markdown（docs/reports/verification-<date>.md）。"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TARGETS = {"gain": ("dB", 60.0, True), "gbw": ("MHz", 10.0, True),
           "pm": ("deg", 60.0, True), "srp": ("V/us", 10.0, True),
           "srm": ("V/us", 10.0, True), "power": ("uW", 1000.0, False)}


def main() -> int:
    sizing = json.loads((ROOT / "runs/2026-11-25-io18-ac/target-result.json").read_text(encoding="utf-8"))
    pvt = list(csv.DictReader((ROOT / "runs/2026-11-25-pvt/pvt.csv").open(encoding="utf-8-sig")))
    mc = list(csv.DictReader((ROOT / "runs/2026-11-26-mc/mc.csv").open(encoding="utf-8-sig")))
    avt = json.loads((ROOT / "runs/2026-11-25-lut-build/13mmrf_io18/avt-source.json").read_text(encoding="utf-8"))
    beta = json.loads((ROOT / "runs/2026-11-25-lut-build/13mmrf_io18/beta-source.json").read_text(encoding="utf-8"))
    noise = json.loads((ROOT / "runs/2026-11-25-lut-build/13mmrf_io18/noise-source.json").read_text(encoding="utf-8"))
    exp = json.loads((ROOT / "runs/2026-11-26-export/netlist-diff.json").read_text(encoding="utf-8")) \
        if (ROOT / "runs/2026-11-26-export/netlist-diff.json").exists() else None

    lines = ["# 迁移验证报告（OPA_D，smic18ee → 13mmrf）", "",
             f"- 日期：2026-11-26",
             f"- 目标：{sizing['pdk']}，{sizing['devices']}",
             f"- 标称条件：{sizing['corner']}，CL={sizing['load_pf']} pF", ""]

    # 标称
    lines += ["## 1. 标称点指标", "", "| 指标 | 实测 | 最低目标 | 判定 |", "|---|---|---|---|"]
    for k, (unit, tgt, is_min) in TARGETS.items():
        v = sizing["metrics"].get(k)
        if v is None:
            continue
        ok = v >= tgt if is_min else v <= tgt
        lines.append(f"| {k} | {v:.3g} {unit} | {'≥' if is_min else '≤'}{tgt:g} | {'✅' if ok else '❌'} |")
    lines.append("")

    # PVT
    lines += ["## 2. PVT 45 点（5 process × 3 VDD × 3 temp）", "",
              "| 指标 | 最坏值 | 位置 | 最低目标 | 判定 |", "|---|---|---|---|---|"]
    for k, (unit, tgt, is_min) in TARGETS.items():
        vals = [(float(r[k]), r["case"]) for r in pvt if k in r]
        if not vals:
            continue
        worst = min(vals) if is_min else max(vals)
        ok = worst[0] >= tgt if is_min else worst[0] <= tgt
        lines.append(f"| {k} | {worst[0]:.3g} {unit} | {worst[1]} | {'≥' if is_min else '≤'}{tgt:g} | {'✅' if ok else '❌'} |")
    lines.append("")

    # MC
    lines += ["## 3. 蒙卡 300 点（Pelgrom Vt 失配）", "",
              "| 指标 | 均值 | σ | 单指标通过率 |", "|---|---|---|---|"]
    for k, (unit, tgt, is_min) in TARGETS.items():
        vals = [float(r[k]) for r in mc if k in r]
        if not vals:
            continue
        mean = statistics.mean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        passed = sum(1 for v in vals if (v >= tgt if is_min else v <= tgt))
        lines.append(f"| {k} | {mean:.4g} {unit} | {sd:.3g} | {100*passed/len(vals):.1f}% |")
    lines.append("")

    # 完整统计蒙卡
    mcf = ROOT / "runs/2026-11-26-mc-full/mc.csv"
    if mcf.exists():
        mcf_rows = list(csv.DictReader(mcf.open(encoding="utf-8-sig")))
        lines += ["## 3b. 完整统计蒙卡（tox/L/Vth/µ0 四项失配，300 点）", "",
                  "| 指标 | 均值 | σ | 单指标通过率 |", "|---|---|---|---|"]
        for k, (unit, tgt, is_min) in TARGETS.items():
            vals = [float(r[k]) for r in mcf_rows if k in r]
            if not vals:
                continue
            mean = statistics.mean(vals)
            sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
            passed = sum(1 for v in vals if (v >= tgt if is_min else v <= tgt))
            lines.append(f"| {k} | {mean:.4g} {unit} | {sd:.3g} | {100*passed/len(vals):.1f}% |")
        lines.append("")

    # CMRR / PSRR / offset 角集
    cpo = ROOT / "runs/2026-11-26-cpo/cpo.csv"
    if cpo.exists():
        cpo_rows = list(csv.DictReader(cpo.open(encoding="utf-8-sig")))
        lines += ["## 3c. CMRR / PSRR / offset（45 工况）", "",
                  "| 指标 | 最小 | 最大 | 均值 |", "|---|---|---|---|"]
        for k in ("cmrr_db", "psrr_db", "offset_mv"):
            vals = [float(r[k]) for r in cpo_rows if k in r]
            if not vals:
                continue
            lines.append(f"| {k} | {min(vals):.2f} | {max(vals):.2f} | {statistics.mean(vals):.2f} |")
        lines.append("")

    # 参数提取
    lines += ["## 4. 参数提取来源", "",
              f"- Vt 失配 Avt（mV·µm）：{avt.get('avt_mVum')}（来源 {avt.get('parameter')}）",
              f"- β 失配：{beta.get('formula')}",
              f"- 噪声：{noise.get('model')}（κ={noise.get('kappa')}，B_ref={noise.get('B_ref_V2Hz')}）", ""]

    if exp:
        lines += ["## 5. 原理图→网表一致性", "",
                  f"- 对比：{exp.get('a')} vs {exp.get('b')}",
                  f"- 结论：{'一致 ✅' if exp.get('pass') else '有差异 ❌'}，器件数 {exp.get('devices')}", ""]

    lines += ["## 6. 口径与限制", "",
              "- 蒙卡只含 Vt 失配（Pelgrom），不含 tox/β 失配与 SR；工艺角由 PVT 单独覆盖；",
              "- 噪声列为实测拟合（κ 校准），低频 1/f 依赖拟合系数 B_ref；",
              "- 版图 DRC/LVS/PEX 不在本轮范围。", ""]

    out = ROOT / "docs/reports/verification-2026-11-26.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())