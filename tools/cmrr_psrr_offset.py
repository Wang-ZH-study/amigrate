#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CMRR / PSRR / offset 的 PVT 角集仿真（45 工况）。

每个工况 4 个网表：
  *_ad.scs    开环差模增益 Ad（Vinp AC=1）
  *_cm.scs    开环共模增益 Acm（Vinp 与 Vcm 同时 AC=1）→ CMRR = 20log10(Ad/Acm)
  *_psrr.scs  VDD AC=1 → PSRR = -20log10(|Vout|)
  *_off.scs   单位增益缓冲，Vinp=0.9V → offset = Vout - 0.9V

用法：
  python tools/cmrr_psrr_offset.py --gen
  # scp nets 与 run_cpo.sh 到 VM /tmp/cpo → bash /tmp/cpo/run_cpo.sh
  python tools/cmrr_psrr_offset.py --parse --raw runs/2026-11-26-cpo/raw
"""
from __future__ import annotations

import argparse
import cmath
import csv
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = ROOT / "runs" / "2026-11-26-cpo"
INCLUDE = 'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section={section}'

DEVS = [
    ("M6", "OUT VX VSS VSS", "n33", "42.9u", "1.0u"),
    ("M4", "VX N1 VSS VSS", "n33", "3.87u", "1.0u"),
    ("M3", "N1 N1 VSS VSS", "n33", "3.87u", "1.0u"),
    ("M7", "OUT VBP VDD VDD", "p33", "87.43u", "0.5u"),
    ("M8", "VBP VBP VDD VDD", "p33", "15.77u", "0.5u"),
    ("M2", "VX VINP VTAIL VDD", "p33", "244.2u", "0.5u"),
    ("M1", "N1 VINM VTAIL VDD", "p33", "244.2u", "0.5u"),
    ("M5", "VTAIL VBP VDD VDD", "p33", "15.77u", "0.5u"),
]
PROC = ["tt", "ff", "ss", "fnsp", "snfp"]
VDD_SCALE = [0.9, 1.0, 1.1]
TEMPS = [-40.0, 27.0, 125.0]
VDD_NOM = 1.8


def subckt(proc: str, temp: float) -> list[str]:
    lines = [
        f"// proc={proc} temp={temp:g}",
        "simulator lang=spectre",
        "global 0",
        INCLUDE.format(section=proc),
        f"simulatorOptions options temp={temp:g} tnom=27",
        "",
        "subckt OPA_D OUT VDD VINM VINP VSS",
    ]
    for name, terms, model, w, l in DEVS:
        lines.append(f"    {name} ({terms}) {model} w={w} l={l}")
    lines += [
        "    Rz (OUT NZ) resistor r=2.5K",
        "    Rb (VBP VSS) resistor r=19.31K",
        "    C0 (VX NZ) capacitor c=1.8p",
        "ends OPA_D",
        "",
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
    ]
    return lines


def tb(vdd: float, kind: str) -> list[str]:
    vcm = vdd / 2
    head = [
        f"Vdd (vdd 0) vsource dc={vdd:g}" + (" mag=1" if kind == "psrr" else ""),
        f"Vinp (vinp 0) vsource dc={vcm:g}" + (" mag=1" if kind in ("ad", "cm") else ""),
    ]
    if kind == "off":
        head += ["Vfb (OUT vinn) vsource dc=0", "", "op1 dc", "save OUT"]
        return head
    head += [
        f"Vcm (vcm 0) vsource dc={vcm:g}" + (" mag=1" if kind == "cm" else ""),
        "Lfb (OUT vinn) inductor l=1G",
        "Riso (vinn vcm) resistor r=1k",
        "",
        "ac1 ac start=1 stop=100M dec=5",
        "save OUT",
    ]
    return head


def gen() -> int:
    nets = OUT / "nets"
    nets.mkdir(parents=True, exist_ok=True)
    n = 0
    for proc in PROC:
        for vs in VDD_SCALE:
            for t in TEMPS:
                vdd = VDD_NOM * vs
                base = f"cpo_{proc}_{vs:.1f}_{int(t)}"
                for kind in ("ad", "cm", "psrr", "off"):
                    txt = "\n".join(subckt(proc, t) + tb(vdd, kind)) + "\n"
                    (nets / f"{base}_{kind}.scs").write_text(txt, encoding="utf-8", newline="\n")
                    n += 1
    print(f"生成 {n} 个网表 → {nets}")
    return 0


FREQ = re.compile(r'^"freq"\s+([-\d.eE+]+)\s*$')
COMPLEX = re.compile(r'^"OUT"\s+\(([-\d.eE+]+)\s+([-\d.eE+]+)\)\s*$')
KV = re.compile(r'^"([^"]+)"(?:\s+"[^"]*")?\s+([-\d.eE+]+)\s*$')


def parse_case(d: Path) -> dict:
    raw = d / "net.raw" if (d / "net.raw").is_dir() else d
    out = {}
    ac = raw / "ac1.ac"
    if ac.exists():
        freq, vals = [], []
        for line in ac.read_text(encoding="utf-8", errors="replace").splitlines():
            m = FREQ.match(line)
            if m:
                freq.append(float(m.group(1)))
                continue
            m = COMPLEX.match(line)
            if m:
                vals.append(complex(float(m.group(1)), float(m.group(2))))
        if vals:
            out["gain_1hz"] = abs(vals[0])
    op = raw / "op1.dc"
    if op.exists():
        for line in op.read_text(encoding="utf-8", errors="replace").splitlines():
            m = KV.match(line)
            if m and m.group(1) == "OUT":
                out["vout"] = float(m.group(2))
    return out


def parse(raw: Path) -> int:
    cases: dict[str, dict] = {}
    for d in sorted(raw.iterdir()):
        if not d.is_dir():
            continue
        kind = d.name.rsplit("_", 1)[-1]
        base = d.name.rsplit("_", 1)[0]
        cases.setdefault(base, {}).update({kind: parse_case(d)})
    rows = []
    for base, m in sorted(cases.items()):
        ad = m.get("ad", {}).get("gain_1hz")
        acm = m.get("cm", {}).get("gain_1hz")
        ps = m.get("psrr", {}).get("gain_1hz")
        off = m.get("off", {}).get("vout")
        if not (ad and acm and ps is not None and off is not None):
            continue
        rows.append({
            "case": base,
            "cmrr_db": round(20 * math.log10(ad / acm), 2),
            "psrr_db": round(-20 * math.log10(max(ps, 1e-12)), 2),
            "offset_mv": round((off - 0.9) * 1e3, 2),
        })
    if not rows:
        print(f"没有可解析结果：{raw}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "cpo.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def stat(key):
        vals = [r[key] for r in rows]
        return min(vals), max(vals), sum(vals) / len(vals)

    print("=" * 74)
    print(f"CMRR/PSRR/offset 角集：{len(rows)} 工况")
    print("=" * 74)
    print(f"{'指标':8s}{'min':>10s}{'max':>10s}{'mean':>10s}")
    for k in ("cmrr_db", "psrr_db", "offset_mv"):
        lo, hi, mean = stat(k)
        print(f"{k:8s}{lo:10.2f}{hi:10.2f}{mean:10.2f}")
    lines = ["# CMRR / PSRR / offset 角集结果（2026-11-26）", "",
             "- 45 工况（5 process × 3 VDD × 3 temp），OPA_D v2（n33/p33 @1.8V）", "",
             "| 指标 | 最小 | 最大 | 均值 |", "|---|---|---|---|"]
    for k in ("cmrr_db", "psrr_db", "offset_mv"):
        lo, hi, mean = stat(k)
        lines.append(f"| {k} | {lo:.2f} | {hi:.2f} | {mean:.2f} |")
    lines += ["", "口径：CMRR=20log10(Ad/Acm)，Ad/Acm 取 1Hz 开环增益；PSRR=-20log10(|Vout/VDD|)；",
              "offset 为单位增益缓冲下 Vout-0.9V（输入参考，mV）。", ""]
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n写入 {OUT/'cpo.csv'}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--raw", type=Path, default=OUT / "raw")
    a = ap.parse_args(argv)
    if a.gen:
        return gen()
    if a.parse:
        return parse(a.raw)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))