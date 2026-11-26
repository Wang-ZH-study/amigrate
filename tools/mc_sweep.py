#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""蒙卡仿真（Vt-only 或完整统计失配）。

--mode vt   ：只注入 Vt 失配（σ=Avt/√WL，栅极串 ΔV）
--mode full ：按 PDK 四项失配参数（sigma_mis_a–d）注入：
              dtox → 折算成 ΔVth（Vth·dtox/tox）
              dxl  → 逐管 L 变化
              dvth → 栅极串 ΔV
              du0  → 逐管 W 缩放（β ∝ µ0·W）
每点跑：开环 AC（gain/UGF/PM）+ op（功耗）。

用法：
  python tools/mc_sweep.py --gen --runs 300 --mode full
  # scp nets 与 run_mc.sh 到 VM /tmp/mc → bash /tmp/mc/run_mc.sh
  python tools/mc_sweep.py --parse --raw runs/2026-11-26-mc-full/raw
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pvt_sweep import metrics_case  # noqa: E402

INCLUDE = 'include "/home/IC/Tech/PDK_13mmrf_1P6M_30k/models/spectre/ms013_io33_v2p6_7p_spe.lib" section=tt'

# PDK 失配参数（V·µm / m / 无量纲）；tox 单位 m
PARAMS = {
    "n": {"avth": 9.5e-3, "atox": 4e-11, "axl": 3e-9, "au0": 6e-4, "tox": 7e-9, "vth0": 0.60},
    "p": {"avth": 3.5e-3, "atox": 3e-11, "axl": 3e-10, "au0": 1e-4, "tox": 7e-9, "vth0": 0.65},
}
DEVS = [
    ("M6", "OUT VX VSS VSS", "n33", "n", 42.9, 1.0),
    ("M4", "VX N1 VSS VSS", "n33", "n", 3.87, 1.0),
    ("M3", "N1 N1 VSS VSS", "n33", "n", 3.87, 1.0),
    ("M7", "OUT VBP VDD VDD", "p33", "p", 87.43, 0.5),
    ("M8", "VBP VBP VDD VDD", "p33", "p", 15.77, 0.5),
    ("M2", "VX VINP VTAIL VDD", "p33", "p", 244.2, 0.5),
    ("M1", "N1 VINM VTAIL VDD", "p33", "p", 244.2, 0.5),
    ("M5", "VTAIL VBP VDD VDD", "p33", "p", 15.77, 0.5),
]
TARGETS = {"gain": 60.0, "gbw": 10.0, "pm": 60.0, "power": 1000.0}


def draw(mode: str, typ: str, w: float, l: float, rng: random.Random) -> dict:
    p = PARAMS[typ]
    wl = math.sqrt(max(w * l, 1e-12))
    if mode == "vt":
        return {"dvth": p["avth"] / wl * rng.gauss(0, 1) * 1e-3, "dl": 0.0, "wscale": 1.0}
    za = rng.gauss(0, 1)
    zb = rng.gauss(0, 1)
    zc = rng.gauss(0, 1)
    zd = rng.gauss(0, 1)
    dtox = p["atox"] / wl * za            # m
    dxl = p["axl"] / math.sqrt(w) * zb    # m
    dvth = p["avth"] / wl * zc            # mV
    du0 = p["au0"] / wl * zd              # 无量纲（β 相对变化）
    dvth_tox = p["vth0"] * (dtox / p["tox"])  # V
    return {"dvth": dvth * 1e-3 + dvth_tox, "dl": dxl, "wscale": 1.0 + du0}


def netlist(runs_draw: dict, mode: str) -> str:
    lines = [
        f"// MC run (mode={mode})",
        "simulator lang=spectre",
        "global 0",
        INCLUDE,
        "",
        "subckt OPA_D OUT VDD VINM VINP VSS",
    ]
    for name, terms, model, typ, w, l in DEVS:
        t = terms.split()
        gate = t[1]
        gnode = f"g{name}"
        dd = runs_draw[name]
        lines.append(f"    V{name} ({gate} {gnode}) vsource dc={dd['dvth']:.6g}")
        t[1] = gnode
        l_eff = max(l + dd["dl"] * 1e6, 1e-3)   # µm
        w_eff = max(w * dd["wscale"], 1e-3)
        lines.append(f"    {name} ({' '.join(t)}) {model} w={w_eff:.6g}u l={l_eff:.6g}u")
    lines += [
        "    Rz (OUT NZ) resistor r=2.5K",
        "    Rb (VBP VSS) resistor r=19.31K",
        "    C0 (VX NZ) capacitor c=1.8p",
        "ends OPA_D",
        "",
        "I0 (OUT vdd vinn vinp 0) OPA_D",
        "Cl (OUT 0) capacitor c=5p",
        "Vdd (vdd 0) vsource dc=1.8",
        "Vinp (vinp 0) vsource dc=0.9 mag=1",
        "Vcm (vcm 0) vsource dc=0.9",
        "Lfb (OUT vinn) inductor l=1G",
        "Riso (vinn vcm) resistor r=1k",
        "",
        "op1 dc",
        "ac1 ac start=1 stop=100M dec=5",
        "save OUT Vdd:p",
        "",
    ]
    return "\n".join(lines)


def gen(runs: int, mode: str, out: Path, seed: int = 20261126) -> int:
    rng = random.Random(seed)
    nets = out / "nets"
    nets.mkdir(parents=True, exist_ok=True)
    meta = []
    for r in range(runs):
        draws = {name: draw(mode, typ, w, l, rng) for name, _t, _m, typ, w, l in DEVS}
        (nets / f"mc_{r:04d}.scs").write_text(netlist(draws, mode), encoding="utf-8", newline="\n")
        meta.append({"run": r, **{f"{k}_{p}": round(v, 8) for k, d in draws.items()
                                   for p, v in d.items()}})
    with (out / "run_meta.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(meta[0].keys()))
        w.writeheader()
        w.writerows(meta)
    print(f"生成 {runs} 个蒙卡网表（mode={mode}）→ {nets}（seed={seed}）")
    return 0


def parse(raw: Path, out: Path) -> int:
    rows = []
    for d in sorted(raw.iterdir()):
        if not d.is_dir():
            continue
        m = metrics_case(d)
        if m:
            rows.append({"run": d.name, **{k: round(v, 4) for k, v in m.items()}})
    if not rows:
        print(f"没有可解析结果：{raw}")
        return 1
    with (out / "mc.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def stats(vals):
        n = len(vals)
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / (n - 1) if n > 1 else 0.0
        return mean, math.sqrt(var)

    print("=" * 78)
    print(f"蒙卡结果：{len(rows)} 点（mode={out.name}）")
    print("=" * 78)
    print(f"{'metric':8s}{'mean':>10s}{'sigma':>9s}{'min':>9s}{'max':>9s}{'目标':>8s}{'pass率':>8s}")
    for k, tgt in (("gain", 60.0), ("gbw", 10.0), ("pm", 60.0), ("power", 1000.0)):
        vals = [r[k] for r in rows if k in r]
        if not vals:
            continue
        mean, sd = stats(vals)
        ok = [v <= tgt for v in vals] if k == "power" else [v >= tgt for v in vals]
        print(f"{k:8s}{mean:10.3f}{sd:9.3f}{min(vals):9.3f}{max(vals):9.3f}{tgt:8.1f}{100*sum(ok)/len(ok):7.2f}%")
    joint = sum(1 for r in rows if (r.get("gain", 0) >= 60 and r.get("gbw", 0) >= 10
                                    and r.get("pm", 0) >= 60 and r.get("power", 1e9) <= 1000))
    print(f"\n联合良率：{joint}/{len(rows)} = {100*joint/len(rows):.2f}%")
    lines = [f"# 蒙卡结果（{out.name}）", "",
             f"- 点数：{len(rows)}；mode 见目录名；", "",
             "| 指标 | 均值 | σ | 最小 | 最大 | 目标 | 通过率 |", "|---|---|---|---|---|---|---|"]
    for k, tgt in (("gain", 60.0), ("gbw", 10.0), ("pm", 60.0), ("power", 1000.0)):
        vals = [r[k] for r in rows if k in r]
        if not vals:
            continue
        mean, sd = stats(vals)
        ok = [v <= tgt for v in vals] if k == "power" else [v >= tgt for v in vals]
        lines.append(f"| {k} | {mean:.3f} | {sd:.3f} | {min(vals):.3f} | {max(vals):.3f} | {tgt:g} | "
                     f"{100*sum(ok)/len(ok):.2f}% |")
    lines += ["", f"**联合良率：{joint}/{len(rows)} = {100*joint/len(rows):.2f}%**", ""]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n写入 {out/'mc.csv'}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--mode", choices=["vt", "full"], default="full")
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261126)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--raw", type=Path)
    a = ap.parse_args(argv)
    out = a.out or (ROOT / "runs" / ("2026-11-26-mc-full" if a.mode == "full" else "2026-11-26-mc"))
    if a.gen:
        return gen(a.runs, a.mode, out, a.seed)
    if a.parse:
        return parse(a.raw or (out / "raw"), out)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))