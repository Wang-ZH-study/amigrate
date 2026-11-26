#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""amigrate —— 模拟电路迁移工具链统一入口（v0.9）。

子命令（本地步骤直接执行；需要 VM 的步骤给出命令）：
  amigrate status                查看工程状态与最新结果
  amigrate table --pdk PKG       生成（并提示运行）迁移版器件表
  amigrate solve                 用目标表反解尺寸
  amigrate feasibility           跑 F0–F4 可行性
  amigrate ac                    生成 AC/测量网表（并提示运行）
  amigrate pvt                   生成 PVT 45 点网表（并提示运行）
  amigrate mc --runs 300         生成蒙卡网表（并提示运行）
  amigrate netlist               导出原理图网表（提示 SKILL 命令）
  amigrate judge                 按最低目标判卷
  amigrate report                生成验证报告 Markdown

用法示例：
  python tools/amigrate.py status
  python tools/amigrate.py solve
  python tools/amigrate.py pvt --parse
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
PY = sys.executable


def run(script: str, *args: str) -> int:
    cmd = [PY, str(TOOLS / script), *args]
    print("$ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def read_toml() -> dict:
    import tomllib
    with (ROOT / "amigrate.toml").open("rb") as f:
        return tomllib.load(f)


def cmd_status(_: argparse.Namespace) -> int:
    cfg = read_toml()
    print(f"工程：{cfg['project']['design']}  {cfg['project']['source_pdk']} → {cfg['project']['target_pdk']}")
    print(f"供电：{cfg['project']['vdd_v']}V，负载：{cfg['project']['cload_pf']}pF\n")
    checks = [
        ("目标器件表", cfg["paths"]["lut_target"]),
        ("源器件表", cfg["paths"]["lut_source"]),
        ("尺寸结果", cfg["paths"]["sizing"]),
        ("PVT 结果", cfg["paths"]["pv_result"]),
        ("蒙卡结果", cfg["paths"]["mc_result"]),
    ]
    for name, rel in checks:
        p = ROOT / rel
        print(f"  {'✅' if p.exists() else '❌'} {name:10s} {rel}")
    print("\n最近 runs：")
    runs = sorted((ROOT / "runs").glob("*"))
    for r in runs[-6:]:
        print(f"  - {r.name}")
    return 0


def cmd_table(a: argparse.Namespace) -> int:
    return run("build_migration_lut.py", "--pdk", a.pdk)


def cmd_solve(_: argparse.Namespace) -> int:
    cfg = read_toml()
    return run("solve_sizing_13mmrf.py", "--lut", cfg["paths"]["lut_target"],
               "--out", "runs/2026-11-26-solve")


def cmd_feasibility(a: argparse.Namespace) -> int:
    cfg = read_toml()
    return run("feasibility.py", "--lut", cfg["paths"]["lut_target"],
               "--out", a.out)


def cmd_ac(_: argparse.Namespace) -> int:
    print("生成 AC/测量网表：")
    rc = run("make_io18_testbench.py")
    rc |= run("make_measure_tb.py", "--variant", "tgt")
    print("\n下一步（VM）：")
    print("  scp runs/2026-11-25-io18-ac/{src,tgt}_net.scs ic618:/tmp/")
    print("  ssh ic618 'bash /tmp/run_ac.sh'   # 或 run_meas.sh")
    return rc


def cmd_pvt(a: argparse.Namespace) -> int:
    if a.parse:
        return run("pvt_sweep.py", "--parse", "--raw", "runs/2026-11-25-pvt/raw")
    run("pvt_sweep.py", "--gen")
    print("\n下一步（VM）：")
    print("  scp -r runs/2026-11-25-pvt/nets runs/2026-11-25-pvt/run_pvt.sh ic618:/tmp/pvt/")
    print("  ssh ic618 'bash /tmp/pvt/run_pvt.sh'")
    print("  python tools/amigrate.py pvt --parse")
    return 0


def cmd_mc(a: argparse.Namespace) -> int:
    if a.parse:
        return run("mc_sweep.py", "--parse", "--raw", "runs/2026-11-26-mc/raw")
    run("mc_sweep.py", "--gen", "--runs", str(a.runs))
    print("\n下一步（VM）：")
    print("  scp -r runs/2026-11-26-mc/nets runs/2026-11-26-mc/run_mc.sh ic618:/tmp/mc/")
    print("  ssh ic618 'bash /tmp/mc/run_mc.sh'")
    print("  python tools/amigrate.py mc --parse")
    return 0


def cmd_netlist(_: argparse.Namespace) -> int:
    print("原理图→网表（需 Virtuoso）：")
    print("  scp skill/export_netlist.il ic618:/tmp/")
    print("  ssh ic618 'cd /home/IC && timeout 180 virtuoso -nograph < /tmp/export_netlist.il'")
    print("  scp ic618:/home/IC/port_pilot/opa_d_export.scs runs/2026-11-26-export/")
    print("  python tools/netlist_diff.py --a runs/2026-11-26-export/opa_d_export.scs --b runs/2026-11-25-pvt/nets/pvt_tt_1.0_27_ac.scs")
    return 0


def cmd_judge(_: argparse.Namespace) -> int:
    cfg = read_toml()
    return run("check_spec.py", "--judge-abs", cfg["paths"]["sizing"])


def cmd_report(_: argparse.Namespace) -> int:
    return run("gen_report.py")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="amigrate —— 模拟电路迁移工具链")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("table")
    p.add_argument("--pdk", default="13mmrf_io18")
    p.set_defaults(func=cmd_table)

    sub.add_parser("solve").set_defaults(func=cmd_solve)

    p = sub.add_parser("feasibility")
    p.add_argument("--out", default="runs/2026-11-26-feasibility")
    p.set_defaults(func=cmd_feasibility)

    sub.add_parser("ac").set_defaults(func=cmd_ac)

    p = sub.add_parser("pvt")
    p.add_argument("--parse", action="store_true")
    p.set_defaults(func=cmd_pvt)

    p = sub.add_parser("mc")
    p.add_argument("--parse", action="store_true")
    p.add_argument("--runs", type=int, default=300)
    p.set_defaults(func=cmd_mc)

    sub.add_parser("netlist").set_defaults(func=cmd_netlist)
    sub.add_parser("judge").set_defaults(func=cmd_judge)
    sub.add_parser("report").set_defaults(func=cmd_report)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))