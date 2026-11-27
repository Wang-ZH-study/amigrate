#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PDK 发现：扫描 VM 上的任意 PDK，产出通用 LUT 构建配置（JSON）。

做法（启发式，结果需人看一遍）：
  1. 在 PDK 根目录下找 Spectre 模型文件（*.lib/*.scs/*.ckt）；
  2. 从 section=xxx 提取工艺角；
  3. 从 `subckt <name> d g s b` 识别四端器件，按名字首字母分 n/p；
  4. 提取失配参数 avth/atox/axl/au0/tox；
  5. 生成与 build_lut_generic.py 兼容的配置：includes / devs / vgs_max / Ls / vds / vsb。

用法：
  python tools/pdk_discover.py --pdk PDK_13mmrf_1P6M_30k
  python tools/pdk_discover.py --pdk CSMC_18 --root /home/IC/Tech/CSMC_18
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SSH = "ic618"
CREATE_NO_WINDOW = 0x08000000
SUBKW = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
VM_TECH = "/home/IC/Tech"

SUBCKT_RE = re.compile(r'^\s*(?:inline\s+)?subckt\s+(\w+)\s+(.+)$', re.I)
MODEL_RE = re.compile(r'^\s*(?:model|\.model)\s+(\w+)\s+(\w+)', re.I)
SECTION_RE = re.compile(r'section[= ]+([A-Za-z0-9_]+)')
PARAM_RE = re.compile(r'parameters?\s+(avth|atox|axl|au0|tox|vth0)[_A-Za-z0-9]*\s*=\s*([-\d.eE+]+)')


def ssh(cmd: str, timeout: int = 120) -> tuple[int, str]:
    p = subprocess.run(["ssh", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=8", SSH, cmd],
                       capture_output=True, text=True, timeout=timeout, **SUBKW)
    out = p.stdout or ""
    if p.returncode != 0:
        out += "\n" + (p.stderr or "")
    return p.returncode, out


def shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def find_models(pdk_root: str) -> list[str]:
    rc, out = ssh(f"find {shq(pdk_root)} -maxdepth 5 \\( -name '*.lib' -o -name '*.scs' -o -name '*.ckt' -o -name '*.mdl' \\) "
                  f"-type f 2>/dev/null | head -200")
    return [l.strip() for l in out.splitlines() if l.strip().startswith("/")]


def probe_file(path: str) -> dict:
    rc, out = ssh(f"grep -l 'section' {shq(path)} 2>/dev/null; "
                  f"grep -oE 'section[= ]+[A-Za-z0-9_]+' {shq(path)} 2>/dev/null | sort -u | head -40; "
                  f"echo '---SUBCKT'; grep -iE '^[[:space:]]*(inline[[:space:]]+)?subckt[[:space:]]+' {shq(path)} 2>/dev/null | head -160; "
                  f"echo '---MODEL'; grep -iE '^\\s*(model|\\.model)\\s+' {shq(path)} 2>/dev/null | head -120; "
                  f"echo '---PARAM'; grep -ioE 'parameters?\\s+(avth|atox|axl|au0|tox)[_A-Za-z0-9]*\\s*=\\s*[0-9.eE+-]+' "
                  f"{shq(path)} 2>/dev/null | head -40")
    parts = {"has_section": False, "corners": [], "subckts": [], "models": [], "params": {}}
    seg = "head"
    for line in out.splitlines():
        s = line.strip()
        if s == "---SUBCKT":
            seg = "subckt"; continue
        if s == "---MODEL":
            seg = "model"; continue
        if s == "---PARAM":
            seg = "param"; continue
        if not s:
            continue
        if seg == "head":
            if s == path:
                parts["has_section"] = True
            m = SECTION_RE.search(s)
            if m and m.group(1) not in parts["corners"]:
                parts["corners"].append(m.group(1))
        elif seg == "subckt":
            m = SUBCKT_RE.match(s)
            if m:
                parts["subckts"].append({"name": m.group(1),
                                       "ports": m.group(2).replace("(", " ").replace(")", " ").split()})
        elif seg == "model":
            m = MODEL_RE.match(s)
            if m:
                parts["models"].append({"name": m.group(1), "type": m.group(2)})
        elif seg == "param":
            m = PARAM_RE.search(s)
            if m and m.group(1) not in parts["params"]:
                parts["params"][m.group(1)] = float(m.group(2))
    return parts


def infer_voltage(name: str, default: float = 1.8) -> float:
    m = re.match(r'^[np](\d{2})', name)
    if not m:
        return default
    code = m.group(1)
    table = {"12": 1.2, "18": 1.8, "25": 2.5, "33": 3.3, "50": 5.0, "65": 1.0}
    return table.get(code, default)


def is_mos_subckt(item: dict) -> bool:
    """四端、名字像 MOS 的 subckt（排除 res/cap/dio/bip 等）。"""
    name = item["name"].lower()
    if len(item["ports"]) != 4:
        return False
    if not name.startswith(("n", "p")):
        return False
    if any(k in name for k in ("dio", "res", "cap", "npn", "pnp", "esd", "wdio", "dti", "inductor")):
        return False
    base = re.sub(r"(_mis_ckt|_ckt|_rf|_3t|_ckt_rf)$", "", name)
    return bool(re.match(r"^[np](ch|mos)?[0-9]*$", base))


def pick_devices(subckts: list[dict], models: list[dict]) -> dict:
    """返回 {'n': name, 'p': name}：四端 subckt 优先，其次 model。"""
    devs = {}
    for item in subckts:
        if not is_mos_subckt(item):
            continue
        devs.setdefault(item["name"].lower()[0], item["name"])
    for item in models:
        low = item["name"].lower()
        if low.startswith(("n", "p")) and low[0] not in devs and low not in ("n", "p"):
            devs.setdefault(low[0], item["name"])
    return devs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", required=True)
    ap.add_argument("--root", default=None)
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--devs", nargs=2, metavar=("N_DEV", "P_DEV"), default=None,
                    help="手工指定 n/p 器件名（如 n33_mis_ckt p33_mis_ckt）")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    pdk_root = a.root or f"{VM_TECH}/{a.pdk}"
    rc, out = ssh(f"test -d {shq(pdk_root)} && echo OK")
    if "OK" not in out:
        print(f"❌ PDK 目录不存在：{pdk_root}")
        return 1

    files = find_models(pdk_root)
    print(f"发现 {len(files)} 个候选模型文件")
    probed = []
    for f in files:
        info = probe_file(f)
        if info["subckts"] or info["models"] or info["has_section"]:
            probed.append((f, info))

    def mos_count(info: dict) -> int:
        return len([s for s in info["subckts"] if is_mos_subckt(s)])

    def _rf_penalty(f: str) -> int:
        low = f.lower()
        return 25 if "_rf" in low else (
            12 if any(k in low for k in ("res_spe", "cap_spe", "dio", "bip", "ind_spe")) else 0)

    # 角文件：优先带 section 的；器件文件：优先带 MOS 的（两者可以不同）
    corner_files = [(f, i) for f, i in probed if i["has_section"]]
    corner_files.sort(key=lambda x: (
        1 if any(c.lower() in ("tt", "typical") for c in x[1]["corners"]) else 0,
        -_rf_penalty(x[0]),
        len(x[1]["corners"]),
        6 if x[1]["params"] else 0), reverse=True)
    dev_files = [(f, i) for f, i in probed if mos_count(i) > 0]
    dev_files.sort(key=lambda x: (
        mos_count(x[1]) - _rf_penalty(x[0]) * 2,
        4 if x[1]["has_section"] else 0), reverse=True)

    if not corner_files and not dev_files:
        print("❌ 未找到含器件/工艺角的模型文件")
        return 1
    mfile, info = (corner_files or dev_files)[0]
    if corner_files and mos_count(corner_files[0][1]) > 0:
        # 角文件本身定义了器件（如 13mmrf 的 spe.lib）→ 优先同文件
        dfile, dinfo = corner_files[0]
    elif dev_files:
        dfile, dinfo = dev_files[0]
    else:
        dfile, dinfo = mfile, info
    all_mos = sorted({s["name"] for s in dinfo["subckts"] if is_mos_subckt(s)})
    devs = pick_devices(dinfo["subckts"], dinfo["models"])
    if a.devs:
        devs = {"n": a.devs[0], "p": a.devs[1]}
    corners = info["corners"] or dinfo["corners"]
    print(f"角文件：{mfile}")
    print(f"器件文件：{dfile}")
    print(f"工艺角：{corners[:12]}")
    print(f"器件：{devs}")

    includes = [f'include "{mfile}" section={a.corner if a.corner in corners else (corners[0] if corners else "tt")}']
    if dfile != mfile:
        includes.append(f'include "{dfile}"')
    info = {**info, "corners": corners}

    cfg = {
        "pdk": a.pdk,
        "root": pdk_root,
        "model_file": mfile,
        "device_file": dfile,
        "includes": includes,
        "corner": a.corner if a.corner in corners else (corners[0] if corners else "tt"),
        "corners": corners,
        "devs": devs,
        "device_candidates": all_mos,
        "vdd": 1.8,
        "vgs_max": min(infer_voltage(devs.get("n", "n18")), 1.8),
        "Ls": [0.5, 1.0, 2.0],
        "vds": [0.3, 0.9],
        "vsb": [0.0, 0.3],
        "vgs_step": 0.05,
        "inst_extra": " mr=1 mismod=0" if "_mis_ckt" in json.dumps(devs) else "",
        "as_ad": False,
        "params": info["params"],
        "source": "pdk_discover.py（启发式）",
        "warnings": [],
    }
    if not devs:
        cfg["warnings"].append("未自动识别 n/p 器件，需要手工填 devs")
    if not info["corners"]:
        cfg["warnings"].append("未发现 section，需要手工挑 include 与角名")

    odir = a.out or (ROOT / "runs" / "2026-11-27-generic" / "discover")
    odir.mkdir(parents=True, exist_ok=True)
    ofile = odir / f"{a.pdk}.json"
    ofile.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 写入 {ofile}")
    if cfg["warnings"]:
        for w in cfg["warnings"]:
            print("  ⚠ " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))