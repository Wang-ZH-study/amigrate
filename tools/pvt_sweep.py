#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""工单 09：OPA_D（13mmrf n33/p33，n-L=1.0µm）PVT 45 点扫描。

每个工况生成两个网表：
  *_ac.scs  —— 开环 AC（L 反馈 + 1k 隔离），测 gain / UGF / PM
  *_buf.scs —— 单位增益缓冲（op + 阶跃 tran），测 power / SR+ / SR-

用法：
  python tools/pvt_sweep.py --gen
  # scp runs/2026-11-25-pvt/nets/* 与 run_pvt.sh 到 VM /tmp/pvt/，bash /tmp/pvt/run_pvt.sh
  python tools/pvt_sweep.py --parse --raw runs/2026-11-25-pvt/raw

注意：process 角段名（tt/ff/ss/fnsp/snfp）目前按 spec 命名写死，VM 恢复后先用
  grep -inE 'section' <lib> 核对；如实际是 mos_tt 之类，用 --sections 或改 PROC_SECTIONS。
"""
from __future__ import annotations

import argparse
import cmath
import csv as _csv
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runs" / "2026-11-25-pvt"

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

PROC_SECTIONS = ["tt", "ff", "ss", "fnsp", "snfp"]
VDD_SCALE = [0.9, 1.0, 1.1]
TEMPS = [-40.0, 27.0, 125.0]
VDD_NOM = 1.8

ABS = {"gain": 60.0, "gbw": 10.0, "pm": 60.0, "srp": 10.0, "srm": 10.0, "power": 1000.0}


def _head(proc: str, vdd: float, temp: float, tag: str) -> list[str]:
    return [
        f"// OPA_D PVT proc={proc} vdd={vdd:g} temp={temp:g} tb={tag}",
        "simulator lang=spectre",
        "global 0",
        INCLUDE.format(section=proc),
        f"simulatorOptions options temp={temp:g} tnom=27",
        "",
        "subckt OPA_D OUT VDD VINM VINP VSS",
    ]


def _subckt() -> list[str]:
    lines = []
    for name, terms, model, w, l in DEVS:
        lines.append(f"    {name} ({terms}) {model} w={w} l={l}")
    return lines + [
        "    Rz (OUT NZ) resistor r=2.5K",
        "    Rb (VBP VSS) resistor r=19.31K",
        "    C0 (VX NZ) capacitor c=1.8p",
        "ends OPA_D",
        "",
    ]


def netlist_ac(proc: str, vdd: float, temp: float) -> str:
    vcm = vdd / 2
    lines = _head(proc, vdd, temp, "ac") + _subckt() + [
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        f"Vdd (vdd 0) vsource dc={vdd:g}",
        f"Vinp (vinp 0) vsource dc={vcm:g} mag=1",
        f"Vcm (vcm 0) vsource dc={vcm:g}",
        "Lfb (OUT vinn) inductor l=1G",
        "Riso (vinn vcm) resistor r=1k",
        "",
        "ac1 ac start=1 stop=100M dec=10",
        "save OUT",
        "",
    ]
    return "\n".join(lines)


def netlist_buf(proc: str, vdd: float, temp: float) -> str:
    vcm = vdd / 2
    lines = _head(proc, vdd, temp, "buf") + _subckt() + [
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        f"Vdd (vdd 0) vsource dc={vdd:g}",
        f'Vinp (vinp 0) vsource type=pulse val0={vcm-0.4:g} val1={vcm+0.4:g} dc={vcm:g} delay=200n rise=1n fall=1n width=2u period=4u',
        "Vfb (OUT vinn) vsource dc=0",
        "",
        "op1 dc",
        "tran1 tran stop=4u maxstep=0.5n",
        "save OUT vinp Vdd:p",
        "",
    ]
    return "\n".join(lines)


def gen() -> int:
    nets = OUT / "nets"
    nets.mkdir(parents=True, exist_ok=True)
    n = 0
    for proc in PROC_SECTIONS:
        for vs in VDD_SCALE:
            for t in TEMPS:
                vdd = VDD_NOM * vs
                base = f"pvt_{proc}_{vs:.1f}_{int(t)}"
                (nets / f"{base}_ac.scs").write_text(netlist_ac(proc, vdd, t), encoding="utf-8", newline="\n")
                (nets / f"{base}_buf.scs").write_text(netlist_buf(proc, vdd, t), encoding="utf-8", newline="\n")
                n += 2
    print(f"生成 {n} 个网表（45 工况 × 2）→ {nets}")
    return 0


# ---------------- 解析 ----------------
FRE = re.compile(r'^"freq"\s+([-\d.eE+]+)\s*$')
TIME = re.compile(r'^"time"\s+([-\d.eE+]+)\s*$')
COMPLEX = re.compile(r'^"([^"]+)"\s+\(([-\d.eE+]+)\s+([-\d.eE+]+)\)\s*$')
KV = re.compile(r'^"([^"]+)"(?:\s+"[^"]*")?\s+([-\d.eE+]+)\s*$')


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_ac(path: Path):
    freq, out = [], []
    for line in _lines(path):
        m = FRE.match(line)
        if m:
            freq.append(float(m.group(1)))
            continue
        m = COMPLEX.match(line)
        if m and m.group(1) == "OUT":
            out.append(complex(float(m.group(2)), float(m.group(3))))
    return freq, out


def parse_op(path: Path) -> dict:
    sig = {}
    for line in _lines(path):
        m = KV.match(line)
        if m:
            sig[m.group(1)] = float(m.group(2))
    return sig


def parse_tran(path: Path):
    t, out = [], []
    for line in _lines(path):
        m = TIME.match(line)
        if m:
            t.append(float(m.group(1)))
            continue
        m = KV.match(line)
        if m and m.group(1) == "OUT":
            out.append(float(m.group(2)))
    return t, out


def metrics_case(d: Path) -> dict:
    r: dict = {}
    base = d / "net.raw" if (d / "net.raw").is_dir() else d
    ac = base / "ac1.ac"
    if ac.exists():
        freq, out = parse_ac(ac)
        if out:
            r["gain"] = 20 * math.log10(abs(out[0]))
            z = dict(zip(freq, out))
            rows = [(f, 20 * math.log10(abs(v))) for f, v in zip(freq, out) if abs(v) > 0]
            for (f1, g1), (f2, g2) in zip(rows, rows[1:]):
                if g1 > 0 >= g2:
                    t = g1 / (g1 - g2) if g1 != g2 else 0
                    ugf = 10 ** (math.log10(f1) + t * (math.log10(f2) - math.log10(f1)))
                    a1 = cmath.phase(z[f1]) * 180 / math.pi
                    a2 = cmath.phase(z[f2]) * 180 / math.pi
                    ang = a1 + t * (a2 - a1)
                    r["gbw"] = ugf / 1e6
                    r["pm"] = 180 + ang if ang < 0 else 180 - ang
                    break
    op = base / "op1.dc"
    if op.exists():
        sig = parse_op(op)
        if "Vdd:p" in sig:
            r["power"] = abs(sig["Vdd:p"]) * 1.8 * 1e6
    tr = base / "tran1.tran.tran"
    if tr.exists():
        t, v = parse_tran(tr)
        srp = srm = 0.0
        for i in range(1, len(t)):
            dv = v[i] - v[i - 1]
            dt = t[i] - t[i - 1]
            if dt > 0:
                if dv > 0:
                    srp = max(srp, dv / dt)
                else:
                    srm = max(srm, -dv / dt)
        r["srp"] = srp * 1e-6
        r["srm"] = srm * 1e-6
    return r


def parse(raw: Path) -> int:
    cases: dict[str, dict] = {}
    for d in sorted(raw.iterdir()):
        if not d.is_dir():
            continue
        m = metrics_case(d)
        if not m:
            continue
        base = d.name.rsplit("_", 1)[0]
        cases.setdefault(base, {}).update(m)
    rows = [{"case": k, **{kk: round(vv, 4) for kk, vv in v.items()}} for k, v in sorted(cases.items())]
    if not rows:
        print(f"没有可解析结果：{raw}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "pvt.csv"
    keys = ["case"] + [k for k in ("gain", "gbw", "pm", "srp", "srm", "power") if any(k in r for r in rows)]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    print("=" * 100)
    print(f"PVT 结果：{len(rows)} 工况")
    print("=" * 100)
    print(f"{'metric':8s}{'min':>10s}{'max':>10s}{'目标':>10s}  判定")
    worst = {}
    for k in ("gain", "gbw", "pm", "srp", "srm", "power"):
        vals = [r[k] for r in rows if k in r]
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        worst[k] = (lo, hi)
        if k == "power":
            ok = hi <= ABS[k]
        else:
            ok = lo >= ABS[k]
        print(f"{k:8s}{lo:10.3f}{hi:10.3f}{ABS[k]:10.1f}  {'PASS' if ok else 'FAIL'}")

    lines = ["# PVT 扫描结果（13mmrf n33/p33，n-L=1.0µm）", "",
             f"- 工况数：{len(rows)}（5 process × 3 VDD × 3 temp）", "",
             "| 指标 | 最小值 | 最大值 | 最低目标 | 判定 |", "|---|---|---|---|---|"]
    for k in ("gain", "gbw", "pm", "srp", "srm", "power"):
        if k not in worst:
            continue
        lo, hi = worst[k]
        ok = hi <= ABS[k] if k == "power" else lo >= ABS[k]
        lines.append(f"| {k} | {lo:.3f} | {hi:.3f} | {ABS[k]:g} | {'PASS' if ok else 'FAIL'} |")
    fail = [k for k in worst if (worst[k][1] > ABS[k] if k == "power" else worst[k][0] < ABS[k])]
    lines += ["", "**结论：" + ("45 工况全部满足最低目标。" if not fail else f"最坏情况不满足：{fail}") + "**", ""]
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n写入 {csv_path}")
    return 0 if not fail else 1


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