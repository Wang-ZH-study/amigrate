#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 OPA_D 的 AC 测试台网表：源设计（smic18ee）与目标（13mmrf n33/p33）。

拓扑取自上游 AC 网表 runs/2026-11-25-io18-ac/upstream_net.scs（OPA_D_AC），
测试台统一为"DC 经大电感闭环、AC 开环"的开环增益测法：
  VINP = VCM(0.9V) + AC 1V；OUT 与 VINM 之间接 1GH 电感（DC 短路、AC 开路）；
  |VOUT|/|VINP| 即开环增益。
输出：runs/2026-11-25-io18-ac/{src,tgt}_net.scs
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runs" / "2026-11-25-io18-ac"

SRC_DEV = {
    # name: (type, w, l, m)
    "M6": ("n", "15.06u", "500n", 1),
    "M4": ("n", "1.36u", "500n", 1),
    "M3": ("n", "1.36u", "500n", 1),
    "M7": ("p", "33.57u", "500n", 2),
    "M8": ("p", "48.43u", "500n", 1),
    "M2": ("p", "9.27u", "500n", 1),
    "M1": ("p", "9.27u", "500n", 1),
    "M5": ("p", "40u", "500n", 1),
}

# 目标尺寸来自 runs/2026-11-25-feasibility-io18（L=0.5µm，W 为总宽）
TGT_DEV = {
    "M6": ("n", "20.42u", "0.5u", 1),
    "M4": ("n", "1.84u", "0.5u", 1),
    "M3": ("n", "1.84u", "0.5u", 1),
    "M7": ("p", "87.43u", "0.5u", 1),
    "M8": ("p", "15.77u", "0.5u", 1),
    "M2": ("p", "244.2u", "0.5u", 1),
    "M1": ("p", "244.2u", "0.5u", 1),
    "M5": ("p", "15.77u", "0.5u", 1),
}

TOPO = [
    ("M6", "OUT VX VSS VSS"),
    ("M4", "VX N1 VSS VSS"),
    ("M3", "N1 N1 VSS VSS"),
    ("M7", "OUT VBP VDD VDD"),
    ("M8", "VBP VBP VDD VDD"),
    ("M2", "VX VINP VTAIL VDD"),
    ("M1", "N1 VINM VTAIL VDD"),
    ("M5", "VTAIL VBP VDD VDD"),
]

INCLUDE_SRC = 'include "/home/IC/Tech/smic18ee_2P6M_20100810/smic18ee/../models/spectre/e2r018_v1p8_spe.scs" section=tt'
INCLUDE_TGT = 'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section=tt'


def netlist(devs: dict, include: str, model_n: str, model_p: str, title: str) -> str:
    lines = [
        f"// {title}",
        "simulator lang=spectre",
        "global 0",
        include,
        "",
        "subckt OPA_D OUT VDD VINM VINP VSS",
    ]
    for name, terminals in TOPO:
        typ, w, l, m = devs[name]
        model = model_n if typ == "n" else model_p
        mstr = f" m={m}" if m != 1 else ""
        lines.append(f"    {name} ({terminals}) {model} w={w} l={l}{mstr}")
    lines += [
        "    Rz (OUT NZ) resistor r=2.5K",
        "    Rb (VBP VSS) resistor r=19.31K",
        "    C0 (VX NZ) capacitor c=1.8p",
        "ends OPA_D",
        "",
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        "Vdd (vdd 0) vsource dc=1.8",
        "Vcm (vcm 0) vsource dc=0.9",
        "Vinp (vinp 0) vsource dc=0.9 mag=1",
        "Lfb (OUT vinn) inductor l=1G",
        "Riso (vinn vcm) resistor r=1k",
        "",
        "op1 dc",
        "ac1 ac start=1 stop=100M dec=10",
        "save OUT vinn vinp",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "src_net.scs").write_text(netlist(SRC_DEV, INCLUDE_SRC, "n18e2r", "p18e2r",
                                             "OPA_D source (smic18ee, upstream sizes)"),
                                     encoding="utf-8", newline="\n")
    (OUT / "tgt_net.scs").write_text(netlist(TGT_DEV, INCLUDE_TGT, "n33", "p33",
                                             "OPA_D target (13mmrf n33/p33, our sizes)"),
                                     encoding="utf-8", newline="\n")
    print(f"写入 {OUT/'src_net.scs'}")
    print(f"写入 {OUT/'tgt_net.scs'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())