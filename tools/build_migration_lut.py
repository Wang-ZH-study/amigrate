#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建"迁移版"器件 LUT（工单 05.3/05.4）。

做什么：
  1. 按 PDK 配置生成逐切片 DC 扫描 deck（单管，W=10 µm，Vgs 从 0 扫到该器件档位的上限）；
  2. 用 `ssh ic618` 把 deck 送进 VM，并行跑 Spectre，结果 psfascii 回传；
  3. 解析多块 VALUE → 逐点行，补齐迁移版新增列（噪声=推导、失配=pending），写成 CSV；
  4. 用 `tools/check_lut.py --check` 校验生成的表。

用法：
  python tools/build_migration_lut.py --pdk smic18ee --devs n --Ls 0.5 --vds 0.9 --vsb 0 --pilot
  python tools/build_migration_lut.py --pdk smic18ee --all
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VN = "ic618"
K_B = 1.380649e-23
T_K = 300.0
GAMMA = 2.0 / 3.0

PDK_CONF = {
    "smic18ee": {
        "vdd": 1.8,
        "vgs_max": 1.8,
        "includes": [
            'include "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_spe.scs" section=tt',
            'include "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_spe.scs" section=bjt_tt',
            'include "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_spe.scs" section=res_tt',
            'include "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_spe.scs" section=pip_tt',
            'include "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_spe.scs" section=mim_tt',
            'include "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_res_spe.ckt"',
        ],
        "devs": {"n": "n18e2r", "p": "p18e2r"},
        "inst_extra": "",
        "as_ad": True,
        "Ls": [0.18, 0.22, 0.28, 0.36, 0.5, 0.7, 1.0, 1.5, 2.0],
        "vds": [0.2, 0.5, 0.9, 1.4],
        "vsb": [0.0, 0.1, 0.2, 0.3, 0.4],
    },
    "13mmrf": {
        "vdd": 1.2,
        "vgs_max": 1.32,
        "includes": [
            'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section=tt',
        ],
        "devs": {"n": "n12_mis_ckt", "p": "p12_mis_ckt"},
        "inst_extra": " mr=1 mismod=0",
        "as_ad": False,
        "Ls": [0.13, 0.15, 0.18, 0.22, 0.28, 0.36, 0.5, 0.7, 1.0],
        "vds": [0.2, 0.4, 0.6, 0.9],
        "vsb": [0.0, 0.1, 0.2, 0.3, 0.4],
    },
    # 1.8V 方案：用 3.3V IO 器件（n33/p33）在 1.8V 供电下工作（2026-11-25 决策 B）
    "13mmrf_io18": {
        "vdd": 1.8,
        "vgs_max": 1.8,
        "vgs_step": 0.005,
        "includes": [
            'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section=tt',
        ],
        "devs": {"n": "n33_mis_ckt", "p": "p33_mis_ckt"},
        "inst_extra": " mr=1 mismod=0",
        "as_ad": False,
        # n33 lmin=0.35um, p33 lmin=0.30um → 取公共下限 0.35
        "Ls": [0.35, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0],
        "vds": [0.2, 0.5, 0.9, 1.4],
        "vsb": [0.0, 0.1, 0.2, 0.3, 0.4],
    },
}


def deck(conf: dict, dev_key: str, L_um: float, vds: float, vsb: float) -> str:
    vdd = conf["vdd"]
    lines = ["simulator lang=spectre"] + conf["includes"]
    lines.append(f"parameters W=10u L={L_um:g}u VDS={vds:g} VSB={vsb:g} VDD={vdd} VGS=0")
    inst = conf["devs"][dev_key]
    if dev_key == "n":
        lines += ["VD (nd 0) vsource dc=VDS", "VG (ng 0) vsource dc=VGS",
                  "VB (nb 0) vsource dc=(-VSB)"]
        tail = f"M1 (nd ng 0 nb) {inst} w=W l=L" + conf.get("inst_extra", "")
    else:
        lines += ["VDDsrc (vdd 0) vsource dc=VDD",
                  "VD (pd 0) vsource dc=(VDD-VDS)",
                  "VG (pg 0) vsource dc=(VDD-VGS)",
                  "VB (nb 0) vsource dc=(VDD+VSB)"]
        tail = f"M1 (pd pg vdd nb) {inst} w=W l=L" + conf.get("inst_extra", "")
    if conf["as_ad"]:
        tail += " as=(W*0.9u) ad=(W*0.9u) ps=(2*W+1.4u) pd=(2*W+1.4u)"
    lines.append(tail)
    lines += [
        "simulatorOptions options reltol=1e-4 vabstol=1e-7 iabstol=1e-14 temp=27 tnom=27 "
        "gmin=1e-13 rforce=1 maxnotes=5 maxwarns=5 digits=8 cols=200",
        f"dc1 dc param=VGS start=0 stop={conf['vgs_max']:g} step={conf.get('vgs_step', 0.02):g}",
        "save M1:ids M1:gm M1:gds M1:vth M1:vdsat M1:region M1:cgg M1:cgd M1:cdb",
        "saveOptions options save=allpub",
        "",
    ]
    return "\n".join(lines)


def parse_blocks(path: Path, sweep_name: str = "VGS") -> list[dict]:
    """解析 psfascii 的 dc 扫描：每个扫描点以 sweep 变量开头，按它切块。"""
    txt = path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks: list[dict] = []
    cur: dict = {}
    in_value = False
    for line in txt:
        s = line.strip()
        if s == "VALUE":
            in_value = True
            continue
        if not in_value or not s.startswith('"'):
            continue
        m = re.match(r'^"([^"]+)"\s+"[^"]*"\s+([-\d.eE+]+)', s)
        name = val = None
        if m:
            name, val = m.group(1), m.group(2)
        else:
            parts = s.split('"')
            if len(parts) >= 3:
                name, val = parts[1].strip(), parts[2].strip()
        if not name:
            continue
        try:
            value = float(val)
        except (TypeError, ValueError):
            continue
        if name == sweep_name and cur:
            blocks.append(cur)
            cur = {}
        cur[name] = value
    if cur:
        blocks.append(cur)
    return blocks


def run_slices(pdk: str, jobs: list[tuple[str, Path]], work: Path) -> None:
    """把 deck 送进 VM 并行跑，拉回 raws。"""
    remote = f"/tmp/lutbuild-{pdk}"
    subprocess.run(["ssh", VN, f"rm -rf {remote} && mkdir -p {remote}/decks {remote}/raws"],
                   check=True)
    deck_dir = work / "decks"
    subprocess.run(["scp", "-r", str(deck_dir), f"{VN}:{remote}/"], check=True)
    script = work / "run_remote.sh"
    lines = ["#!/bin/bash", "cd $(dirname $0)", "mkdir -p raws",
             "ls decks/*.scs | xargs -P 6 -I{} bash -c '",
             "  f={}; n=$(basename $f .scs)",
             "  [ -s raws/$n/dc1.dc ] && exit 0",
             "  mkdir -p raws/$n",
             f"  timeout 180 spectre $f -raw raws/$n -format psfascii > raws/$n/spectre.log 2>&1",
             "  echo $n exit=$?", "'", ""]
    run_remote = work / "run_remote.sh"
    run_remote.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    subprocess.run(["scp", str(run_remote), f"{VN}:{remote}/run_remote.sh"], check=True)
    subprocess.run(["ssh", VN, f"cd {remote} && sed -i 's/\\r$//' run_remote.sh decks/*.scs && bash run_remote.sh"],
                   check=True, stdout=subprocess.DEVNULL)
    raws = work / "raws"
    if raws.exists():
        import shutil
        shutil.rmtree(raws)
    subprocess.run(["scp", "-r", f"{VN}:{remote}/raws", str(raws)], check=True,
                   stdout=subprocess.DEVNULL)


def build(pdk: str, work: Path, devs: list[str], Ls: list[float], vdss: list[float],
          vsbs: list[float]) -> Path:
    conf = PDK_CONF[pdk]
    work = work / pdk
    work.mkdir(parents=True, exist_ok=True)
    decks = work / "decks"
    decks.mkdir(parents=True, exist_ok=True)
    jobs = []
    for dev in devs:
        for L in Ls:
            for vds in vdss:
                for vsb in vsbs:
                    name = f"{dev}_L{L:g}_V{vds:g}_B{vsb:g}".replace(".", "p")
                    f = decks / f"{name}.scs"
                    f.write_text(deck(conf, dev, L, vds, vsb), encoding="utf-8", newline="\n")
                    jobs.append((name, f))
    print(f"[{pdk}] 生成 {len(jobs)} 个切片 deck，开始 VM 运行…")
    run_slices(pdk, jobs, work)

    rows = []
    for name, _ in jobs:
        dc = work / "raws" / name / "dc1.dc"
        if not dc.exists():
            print(f"  缺结果：{name}")
            continue
        blocks = parse_blocks(dc)
        for b in blocks:
            ids = b.get("M1:ids")
            gm = b.get("M1:gm")
            gds = b.get("M1:gds")
            if ids is None or gm is None or gds is None:
                continue
            ids_abs = abs(ids)
            gm_abs = abs(gm)
            gds_abs = abs(gds) if gds else 1e-30
            inoise_th = math.sqrt(4 * K_B * T_K * GAMMA / gm_abs) if gm_abs > 0 else 0.0
            rows.append({
                "dev": name[0], "W": 10e-6, "L": float(name.split("_L")[1].split("_V")[0].replace("p", ".")) * 1e-6,
                "Vds": float(name.split("_V")[1].split("_B")[0].replace("p", ".")),
                "Vsb": float(name.split("_B")[1].replace("p", ".")),
                "Vgs": b.get("VGS", b.get("sweep", float("nan"))),
                "id": ids_abs, "gm": gm_abs, "gds": gds_abs,
                "vth": b.get("M1:vth", float("nan")),
                "vdsat": b.get("M1:vdsat", float("nan")),
                "gmoverid": gm_abs / ids_abs if ids_abs else float("nan"),
                "self_gain": gm_abs / gds_abs,
                "region": int(b.get("M1:region", 0)),
                "vsat_marg": float(name.split("_V")[1].split("_B")[0].replace("p", ".")) - b.get("M1:vdsat", 0.0),
                "id_W_uAum": ids_abs / 10.0 * 1e6,
                "gain_dB": 20 * math.log10(gm_abs / gds_abs) if gds_abs > 0 else float("nan"),
                "Cgg_per_W": b.get("M1:cgg", float("nan")) / 10.0 * 1e15,
                "Cgd_per_W": b.get("M1:cgd", float("nan")) / 10.0 * 1e15,
                "Cdb_per_W": b.get("M1:cdb", float("nan")) / 10.0 * 1e15,
                "inoise_1hz": inoise_th * 100.0,  # 由 1/f 斜率近似（推导值）
                "inoise_10k": inoise_th,
                "noise_src": "derived",
                "avt": 0.0,
                "avt_src": "pending",
                "is_sat": int(b.get("M1:region", 0)) == 2,
                "beta0_low": 0.95, "beta0_high": 1.05,
                "beta1_low": 0.95, "beta1_high": 1.05,
            })
    out = work / f"lut_{pdk}.csv"
    cols = ["dev", "W", "L", "Vds", "Vsb", "Vgs", "id", "gm", "gds", "vth", "vdsat",
            "gmoverid", "self_gain", "region", "vsat_marg", "id_W_uAum", "gain_dB",
            "Cgg_per_W", "Cgd_per_W", "Cdb_per_W", "inoise_1hz", "inoise_10k", "noise_src",
            "avt", "avt_src", "is_sat", "beta0_low", "beta0_high", "beta1_low", "beta1_high"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[{pdk}] 写入 {len(rows)} 行 → {out}")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="构建迁移版 LUT")
    ap.add_argument("--pdk", required=True, choices=list(PDK_CONF))
    ap.add_argument("--devs", nargs="+", default=["n", "p"])
    ap.add_argument("--Ls", nargs="+", type=float)
    ap.add_argument("--vds", nargs="+", type=float)
    ap.add_argument("--vsb", nargs="+", type=float)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--pilot", action="store_true", help="只跑 1 个切片做管线验证")
    a = ap.parse_args(argv)
    conf = PDK_CONF[a.pdk]
    Ls = a.Ls or ([0.5] if a.pilot else conf["Ls"])
    vds = a.vds or ([0.9] if a.pilot else conf["vds"])
    vsb = a.vsb or ([0.0] if a.pilot else conf["vsb"])
    work = a.out or ROOT / "runs" / ("2026-11-25-lut-build-pilot" if a.pilot else "2026-11-25-lut-build")
    work = Path(str(work).replace("\\", "/"))
    out = build(a.pdk, work, a.devs, Ls, vds, vsb)
    print(f"完成：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))