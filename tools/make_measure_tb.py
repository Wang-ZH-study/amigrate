#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 OPA_D 的测量网表（源/目标两版）：

1) meas_{v}_dc_tran.scs —— 单位增益缓冲：op（静态功耗）、dc 扫 ICMR/输出摆幅、tran 大信号阶跃（SR+/SR-）
2) meas_{v}_psrr.scs    —— 开环测试台：VDD 加 AC=1，测电源抑制
3) meas_{v}_thd.scs     —— 缓冲 + 1kHz 正弦，测 THD

v = src（smic18ee 上游尺寸）或 tgt（13mmrf n33/p33，n-L=1.0µm）
输出：runs/2026-11-25-io18-ac/meas/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runs" / "2026-11-25-io18-ac" / "meas"

INC_SRC = 'include "/home/IC/Tech/smic18ee_2P6M_20100810/smic18ee/../models/spectre/e2r018_v1p8_spe.scs" section=tt'
INC_TGT = 'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section=tt'

# name: (type, w, l, m)
SRC = {
    "M6": ("n18e2r", "15.06u", "500n", 1),
    "M4": ("n18e2r", "1.36u", "500n", 1),
    "M3": ("n18e2r", "1.36u", "500n", 1),
    "M7": ("p18e2r", "33.57u", "500n", 2),
    "M8": ("p18e2r", "48.43u", "500n", 1),
    "M2": ("p18e2r", "9.27u", "500n", 1),
    "M1": ("p18e2r", "9.27u", "500n", 1),
    "M5": ("p18e2r", "40u", "500n", 1),
}
TGT = {
    "M6": ("n33", "42.9u", "1.0u", 1),
    "M4": ("n33", "3.87u", "1.0u", 1),
    "M3": ("n33", "3.87u", "1.0u", 1),
    "M7": ("p33", "87.43u", "0.5u", 1),
    "M8": ("p33", "15.77u", "0.5u", 1),
    "M2": ("p33", "244.2u", "0.5u", 1),
    "M1": ("p33", "244.2u", "0.5u", 1),
    "M5": ("p33", "15.77u", "0.5u", 1),
}
TERMS = {
    "M6": "OUT VX VSS VSS",
    "M4": "VX N1 VSS VSS",
    "M3": "N1 N1 VSS VSS",
    "M7": "OUT VBP VDD VDD",
    "M8": "VBP VBP VDD VDD",
    "M2": "VX VINP VTAIL VDD",
    "M1": "N1 VINM VTAIL VDD",
    "M5": "VTAIL VBP VDD VDD",
}


def subckt(devs: dict, title: str) -> list[str]:
    lines = [f"// {title}", "simulator lang=spectre", "global 0",
             INC_SRC if devs is SRC else INC_TGT, "",
             "subckt OPA_D OUT VDD VINM VINP VSS"]
    for name in ("M6", "M4", "M3", "M7", "M8", "M2", "M1", "M5"):
        model, w, l, m = devs[name]
        mstr = f" m={m}" if m != 1 else ""
        lines.append(f"    {name} ({TERMS[name]}) {model} w={w} l={l}{mstr}")
    lines += [
        "    Rz (OUT NZ) resistor r=2.5K",
        "    Rb (VBP VSS) resistor r=19.31K",
        "    C0 (VX NZ) capacitor c=1.8p",
        "ends OPA_D",
        "",
    ]
    return lines


def meas_dc_tran(devs: dict, title: str) -> str:
    lines = subckt(devs, title) + [
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        "Vdd (vdd 0) vsource dc=1.8",
        'Vinp (vinp 0) vsource type=pulse val0=0.4 val1=1.4 dc=0.9 delay=200n rise=1n fall=1n width=2u period=4u',
        "Vfb (OUT vinn) vsource dc=0",
        "",
        "op1 dc",
        "dc1 dc dev=Vinp param=dc start=0.1 stop=1.7 step=0.01",
        "tran1 tran stop=4u maxstep=0.5n",
        "save OUT vinp Vdd:p",
        "",
    ]
    return "\n".join(lines)


def meas_psrr(devs: dict, title: str) -> str:
    lines = subckt(devs, title) + [
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        "Vdd (vdd 0) vsource dc=1.8 mag=1",
        "Vinp (vinp 0) vsource dc=0.9",
        "Lfb (OUT vinn) inductor l=1G",
        "Riso (vinn vcm) resistor r=1k",
        "Vcm (vcm 0) vsource dc=0.9",
        "",
        "ac1 ac start=1 stop=100M dec=10",
        "save OUT vdd",
        "",
    ]
    return "\n".join(lines)


def meas_thd(devs: dict, title: str) -> str:
    lines = subckt(devs, title) + [
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        "Vdd (vdd 0) vsource dc=1.8",
        'Vinp (vinp 0) vsource type=sine dc=0.9 ampl=0.3 freq=1k',
        "Vfb (OUT vinn) vsource dc=0",
        "",
        "tran1 tran stop=5m maxstep=1u",
        "save OUT",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["src", "tgt"], required=True)
    a = ap.parse_args(argv)
    devs, tag = (SRC, "src") if a.variant == "src" else (TGT, "tgt")
    title = "OPA_D source (smic18ee, upstream sizes)" if tag == "src" else "OPA_D target (13mmrf n33/p33, n-L=1.0um)"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"meas_{tag}_dc_tran.scs").write_text(meas_dc_tran(devs, title), encoding="utf-8", newline="\n")
    (OUT / f"meas_{tag}_psrr.scs").write_text(meas_psrr(devs, title), encoding="utf-8", newline="\n")
    (OUT / f"meas_{tag}_thd.scs").write_text(meas_thd(devs, title), encoding="utf-8", newline="\n")
    print(f"写入 {OUT} ({tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))