#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用化器件表构建：按 PDK 发现配置（pdk_discover.py 的 JSON）生成 LUT。

复用 `build_migration_lut.py` 的 deck 模板与 psfascii 解析；器件名、include、
工艺角、电压上限、L/Vds/Vsb 网格都来自发现配置（可在 JSON 里改，也可 CLI 覆盖）。

用法：
  python tools/build_lut_generic.py --cfg runs/2026-11-27-generic/discover/PDK_13mmrf_1P6M_30k.json --pilot
  python tools/build_lut_generic.py --cfg ... --out runs/2026-11-27-generic/lut
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from build_migration_lut import K_B, T_K, GAMMA, deck, parse_blocks, run_slices  # noqa: E402

COLS = ["dev", "W", "L", "Vds", "Vsb", "Vgs", "id", "gm", "gds", "vth", "vdsat",
        "gmoverid", "self_gain", "region", "vsat_marg", "id_W_uAum", "gain_dB",
        "Cgg_per_W", "Cgd_per_W", "Cdb_per_W", "inoise_1hz", "inoise_10k", "noise_src",
        "avt", "avt_src", "is_sat", "beta0_low", "beta0_high", "beta1_low", "beta1_high"]


def make_conf(cfg: dict, devs: dict, Ls, vds, vsb, vgs_max, vgs_step) -> dict:
    inst_extra = cfg.get("inst_extra", "")
    if not inst_extra and any("_mis_ckt" in v for v in devs.values()):
        inst_extra = " mr=1 mismod=0"
    return {
        "vdd": cfg.get("vdd", 1.8),
        "vgs_max": vgs_max,
        "vgs_step": vgs_step,
        "includes": cfg["includes"],
        "devs": devs,
        "inst_extra": inst_extra,
        "as_ad": cfg.get("as_ad", False),
        "Ls": Ls,
        "vds": vds,
        "vsb": vsb,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", type=Path, required=True)
    ap.add_argument("--devs", nargs=2, default=None, metavar=("N", "P"))
    ap.add_argument("--Ls", nargs="+", type=float)
    ap.add_argument("--vds", nargs="+", type=float)
    ap.add_argument("--vsb", nargs="+", type=float)
    ap.add_argument("--vgs-max", type=float)
    ap.add_argument("--vgs-step", type=float)
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    cfg = json.loads(a.cfg.read_text(encoding="utf-8"))
    dev_map = {"n": cfg["devs"]["n"], "p": cfg["devs"]["p"]}
    if a.devs:
        dev_map = {"n": a.devs[0], "p": a.devs[1]}
    Ls = a.Ls or ([0.5] if a.pilot else cfg["Ls"])
    vds = a.vds or ([0.9] if a.pilot else cfg["vds"])
    vsb = a.vsb or ([0.0] if a.pilot else cfg["vsb"])
    vgs_max = a.vgs_max or cfg["vgs_max"]
    vgs_step = a.vgs_step or cfg.get("vgs_step", 0.05)
    out_dir = a.out or (ROOT / "runs" / "2026-11-27-generic" / "lut")
    out_dir = Path(str(out_dir).replace("\\", "/"))
    out_dir.mkdir(parents=True, exist_ok=True)
    conf = make_conf(cfg, dev_map, Ls, vds, vsb, vgs_max, vgs_step)

    decks_dir = out_dir / "decks"
    decks_dir.mkdir(exist_ok=True)
    jobs = []
    for dev in dev_map:
        for L in Ls:
            for vd in vds:
                for vb in vsb:
                    name = f"{dev}_L{L:g}_V{vd:g}_B{vb:g}".replace(".", "p")
                    (decks_dir / f"{name}.scs").write_text(deck(conf, dev, L, vd, vb),
                                                           encoding="utf-8", newline="\n")
                    jobs.append((name, decks_dir / f"{name}.scs"))
    print(f"生成 {len(jobs)} 个切片 deck（{cfg['pdk']}，vgs_max={vgs_max:g}，step={vgs_step:g}）")
    run_slices(cfg["pdk"].replace("/", "_"), jobs, out_dir)

    avt = cfg.get("params", {}).get("avth", 0.0) * 1000  # V·µm → mV·µm
    rows = []
    for name, _ in jobs:
        dc = out_dir / "raws" / name / "dc1.dc"
        if not dc.exists():
            print(f"  缺结果：{name}")
            continue
        for b in parse_blocks(dc):
            ids, gm, gds = b.get("M1:ids"), b.get("M1:gm"), b.get("M1:gds")
            if ids is None or gm is None or gds is None:
                continue
            parts = name.split("_L")[1].split("_V")[0].replace("p", ".")
            Lv = float(parts) * 1e-6
            vdv = float(name.split("_V")[1].split("_B")[0].replace("p", "."))
            vbv = float(name.split("_B")[1].replace("p", "."))
            ids_abs, gm_abs = abs(ids), abs(gm)
            gds_abs = abs(gds) if gds else 1e-30
            inoise_th = math.sqrt(4 * K_B * T_K * GAMMA / gm_abs) if gm_abs > 0 else 0.0
            rows.append({
                "dev": name[0], "W": 10e-6, "L": Lv, "Vds": vdv, "Vsb": vbv,
                "Vgs": b.get("VGS", b.get("sweep", float("nan"))),
                "id": ids_abs, "gm": gm_abs, "gds": gds_abs,
                "vth": b.get("M1:vth", float("nan")), "vdsat": b.get("M1:vdsat", float("nan")),
                "gmoverid": gm_abs / ids_abs if ids_abs else float("nan"),
                "self_gain": gm_abs / gds_abs,
                "region": int(b.get("M1:region", 0)),
                "vsat_marg": vdv - b.get("M1:vdsat", 0.0),
                "id_W_uAum": ids_abs / 10.0 * 1e6,
                "gain_dB": 20 * math.log10(gm_abs / gds_abs) if gds_abs > 0 else float("nan"),
                "Cgg_per_W": b.get("M1:cgg", float("nan")) / 10.0 * 1e15,
                "Cgd_per_W": b.get("M1:cgd", float("nan")) / 10.0 * 1e15,
                "Cdb_per_W": b.get("M1:cdb", float("nan")) / 10.0 * 1e15,
                "inoise_1hz": inoise_th * 100.0, "inoise_10k": inoise_th,
                "noise_src": "derived", "avt": avt, "avt_src": "pdk_model",
                "is_sat": int(b.get("M1:region", 0)) == 2,
                "beta0_low": 0.95, "beta0_high": 1.05,
                "beta1_low": 0.95, "beta1_high": 1.05,
            })
    out_csv = out_dir / f"lut_{cfg['pdk'].replace('/', '_')}.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"✅ 写入 {len(rows)} 行 → {out_csv}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))