#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LUT × Spectre 点抽样验证（05.3/05.6 的补充：证明表本身物理正确）。

两个阶段：
  --gen    从 LUT 随机抽点 + 生成单点 Spectre deck（A 档），另生成 M1/M6 的反解抽检 deck（B 档）
  --parse  解析 VM 回传的 psfascii 结果，与表值比对，出 results.csv + README.md

用法：
  python tools/lut_spotcheck.py --gen   --out runs/2026-11-25-lut-spotcheck
  python tools/lut_spotcheck.py --parse --out runs/2026-11-25-lut-spotcheck

说明：脚本在 Windows 跑；VM（ssh ic618）只负责执行 decks 里的 spectre 命令。
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve_lw import Lut, solve_LW  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDK = "/home/IC/Tech/smic18ee_2P6M_20100810/models/spectre"
INCLUDES = [
    f'include "{PDK}/e2r018_v1p8_spe.scs" section=tt',
    f'include "{PDK}/e2r018_v1p8_spe.scs" section=bjt_tt',
    f'include "{PDK}/e2r018_v1p8_spe.scs" section=res_tt',
    f'include "{PDK}/e2r018_v1p8_spe.scs" section=pip_tt',
    f'include "{PDK}/e2r018_v1p8_spe.scs" section=mim_tt',
    f'include "{PDK}/e2r018_v1p8_res_spe.ckt"',
]
DEFAULT_LUT = Path(r"E:\IC-design-first\exchange\gmid\gmid_table.csv")
DEFAULT_SIZING = Path(r"E:\IC-design-first\week_two\02_sizing\sizing_D.csv")


def _u(v: float) -> str:
    """数值转 spectre 参数串。"""
    return f"{v:.6g}"


def deck(dev: str, L_m: float, W_um: float, vds: float, vsb: float, vgs: float,
         inst: str = "M1") -> str:
    lines = ["simulator lang=spectre"] + INCLUDES + [
        f"parameters W={_u(W_um)}u L={_u(L_m * 1e6)}u VDS={_u(vds)} VSB={_u(vsb)} VGS={_u(vgs)}",
    ]
    if dev == "n":
        lines += [
            "VD (nd 0) vsource dc=VDS",
            "VG (ng 0) vsource dc=VGS",
            "VB (nbulk 0) vsource dc=(-VSB)",
            f"{inst} (nd ng 0 nbulk) n18e2r w=W l=L \\",
            "    as=(W*0.9018181u) ad=(W*0.9018181u) \\",
            "    ps=(2.0*W+1.44u) pd=(2.0*W+1.44u) m=1",
        ]
    else:
        lines += [
            "VDD (vdd 0) vsource dc=1.8",
            "VDP (pd 0) vsource dc=(1.8-VDS)",
            "VGP (pg 0) vsource dc=(1.8-VGS)",
            "VBP (pbulk 0) vsource dc=(1.8+VSB)",
            f"{inst} (pd pg vdd pbulk) p18e2r w=W l=L \\",
            "    as=(W*0.48u) ad=(W*0.48u) \\",
            "    ps=(2.0*W+0.96u) pd=(2.0*W+0.96u) m=1",
        ]
    lines += [
        "simulatorOptions options reltol=1e-4 vabstol=1e-7 iabstol=1e-14 temp=27 tnom=27 "
        "scalem=1.0 scale=1.0 gmin=1e-13 rforce=1 maxnotes=5 maxwarns=5 digits=8 cols=200 pivrel=1e-4",
        "dc1 dc",
        f"save {inst}:ids {inst}:gm {inst}:gds {inst}:vth {inst}:vdsat {inst}:vgs {inst}:vds",
        "saveOptions options save=allpub",
        "",
    ]
    return "\n".join(lines)


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def gen(lut_path: Path, sizing_path: Path, out: Path, n: int, seed: int) -> int:
    rows = [r for r in load_rows(lut_path) if r["region"] == "2"]
    rng = random.Random(seed)
    # 分层：n / p 各一半，尽量覆盖不同 L 与 Vds
    by_dev = {"n": [r for r in rows if r["dev"] == "n"], "p": [r for r in rows if r["dev"] == "p"]}
    picked: list[dict] = []
    for dev in ("n", "p"):
        pool = by_dev[dev]
        seen_L = set()
        # 先按 L 各抽 1-2 个，再补齐
        rng.shuffle(pool)
        for r in pool:
            if len([x for x in picked if x["dev"] == dev]) >= n // 2:
                break
            if r["L"] not in seen_L or len(seen_L) >= 5:
                seen_L.add(r["L"])
                picked.append(r)
        while len([x for x in picked if x["dev"] == dev]) < n // 2:
            picked.append(rng.choice(pool))

    decks = out / "decks"
    decks.mkdir(parents=True, exist_ok=True)
    pts = []
    for i, r in enumerate(picked, start=1):
        name = f"a{i:02d}_{r['dev']}"
        (decks / f"{name}.scs").write_text(
            deck(r["dev"], float(r["L"]), 10.0, float(r["Vds"]), float(r["Vsb"]), float(r["Vgs"])),
            encoding="utf-8", newline="\n")
        pts.append({
            "name": name, "phase": "A", "dev": r["dev"], "L_m": float(r["L"]),
            "Vds": float(r["Vds"]), "Vsb": float(r["Vsb"]), "Vgs": float(r["Vgs"]),
            "id_table": float(r["id"]), "gm_table": float(r["gm"]),
            "vth_table": float(r["vth"]), "self_gain_table": float(r["self_gain"]),
            "W_um": 10.0,
        })

    # ---- B 档：M1(p) 与 M6(n) 按反解尺寸做单管抽检 ----
    lut = Lut(load_rows(lut_path))
    sizing = {r["name"]: r for r in load_rows(sizing_path)}
    for tag in ("M1", "M6"):
        d = sizing[tag]
        id_t = float(d["Id_uA"]) * 1e-6
        gmid = float(d["gmid"])
        sg = 10 ** (float(d["Aint_dB"]) / 20)
        best = None
        for vds in lut.vds_values(d["type"]):
            c = solve_LW(lut, d["type"], {"id": id_t, "gm": gmid * id_t, "self_gain": sg},
                         vds, float(d["Vsb"]))
            if c:
                cand = min(c, key=lambda x: abs(x["L_um"] - float(d["L_um"])))
                if best is None or cand["residual"] < best[1]["residual"]:
                    best = (vds, cand)
        if not best:
            print(f"B 档 {tag}: 反解无候选，跳过")
            continue
        vds, cand = best
        name = f"b_{tag}"
        (decks / f"{name}.scs").write_text(
            deck(d["type"], float(d["L_um"]) * 1e-6, cand["W_um"], vds,
                 float(d["Vsb"]), cand["Vgs"]), encoding="utf-8", newline="\n")
        pts.append({
            "name": name, "phase": "B", "dev": d["type"], "L_m": float(d["L_um"]) * 1e-6,
            "Vds": vds, "Vsb": float(d["Vsb"]), "Vgs": cand["Vgs"],
            "id_table": id_t, "gm_table": gmid * id_t, "vth_table": "",
            "self_gain_table": sg, "W_um": cand["W_um"],
            "gmid_target": gmid, "design": tag,
        })

    with (out / "points.csv").open("w", encoding="utf-8-sig", newline="") as f:
        keys = sorted({k for p in pts for k in p})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(pts)

    (out / "run_all.sh").write_text(
        "#!/bin/bash\nset -u\ncd \"$(dirname \"$0\")\"\nmkdir -p raws\n"
        "for f in decks/*.scs; do\n"
        "  n=$(basename \"$f\" .scs)\n"
        "  if [ -s \"raws/$n/dc.dc\" ]; then echo \"SKIP $n\"; continue; fi\n"
        "  mkdir -p \"raws/$n\"\n"
        "  timeout 120 spectre \"$f\" -raw \"raws/$n\" -format psfascii > \"raws/$n/spectre.log\" 2>&1\n"
        "  echo \"$n exit=$?\"\n"
        "done\n", encoding="utf-8", newline="\n")
    print(f"生成 {len(pts)} 个点（A 档 {n} + B 档 {len(pts) - n}），deck 在 {decks}")
    return 0


def parse_value_block(path: Path) -> dict[str, float]:
    """解析 psfascii 的 VALUE 段（取第一块，单点 dc）。"""
    vals: dict[str, float] = {}
    in_value = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s == "VALUE":
            if in_value and vals:
                break  # 只取第一块（单点 dc）
            in_value = True
            continue
        if not in_value:
            continue
        if s.startswith('"'):
            # 两种格式："name" value  或  "name" "unit" value PROP(...)
            m = re.match(r'^"([^"]+)"\s+"[^"]*"\s+([-\d.eE+]+)', s)
            if m:
                try:
                    vals[m.group(1)] = float(m.group(2))
                except ValueError:
                    pass
                continue
            parts = s.split('"')
            if len(parts) >= 3:
                try:
                    vals[parts[1].strip()] = float(parts[2].strip())
                except ValueError:
                    pass
    return vals


def parse(out: Path, lut_path: Path) -> int:
    pts = load_rows(out / "points.csv")
    res = []
    for p in pts:
        rawdir = out / "raws" / p["name"]
        cand = sorted(rawdir.glob("*.dc")) if rawdir.exists() else []
        if not cand:
            res.append({**p, "status": "missing_raw"})
            continue
        raw = cand[0]
        v = parse_value_block(raw)
        inst = "M1"
        ids = abs(v.get(f"{inst}:ids", float("nan")))
        gm = abs(v.get(f"{inst}:gm", float("nan")))
        gds = abs(v.get(f"{inst}:gds", 1e-30))
        vth = v.get(f"{inst}:vth", float("nan"))
        row = {**p, "id_sim": ids, "gm_sim": gm, "vth_sim": vth,
               "self_gain_sim": gm / gds if gds else float("nan")}
        if p["phase"] == "A":
            id_e = abs(ids / float(p["id_table"]) - 1)
            gm_e = abs(gm / float(p["gm_table"]) - 1)
            vth_e = abs(vth - float(p["vth_table"])) * 1e3
            sg_e = abs(row["self_gain_sim"] / float(p["self_gain_table"]) - 1)
            ok = id_e <= 0.01 and gm_e <= 0.03 and vth_e <= 5 and sg_e <= 0.05
            row.update(id_err=id_e, gm_err=gm_e, vth_err_mV=vth_e, sg_err=sg_e,
                       status="pass" if ok else "fail")
        else:
            gmid_sim = gm / ids if ids else float("nan")
            gmid_t = float(p["gmid_target"])
            gm_e = abs(gmid_sim / gmid_t - 1)
            id_e = abs(ids / float(p["id_table"]) - 1)
            ok = gm_e <= 0.03 and id_e <= 0.05
            row.update(gmid_sim=gmid_sim, gmid_err=gm_e, id_err=id_e,
                       status="pass" if ok else "fail")
        res.append(row)

    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        keys = sorted({k for r in res for k in r})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(res)

    a = [r for r in res if r["phase"] == "A"]
    b = [r for r in res if r["phase"] == "B"]
    a_ok = [r for r in a if r.get("status") == "pass"]
    b_ok = [r for r in b if r.get("status") == "pass"]

    print("=" * 78)
    print(f"A 档（点抽样）：{len(a_ok)}/{len(a)} 通过")
    print("=" * 78)
    print(f"{'点':10s} {'dev':3s} {'L(µm)':>6s} {'Vds':>4s} {'Vsb':>3s} {'Vgs':>5s} "
          f"{'id误差':>7s} {'gm误差':>7s} {'vth误差':>7s} {'SG误差':>7s} 状态")
    for r in a:
        if r.get("status") == "missing_raw":
            print(f"{r['name']:10s} 缺原始结果")
            continue
        print(f"{r['name']:10s} {r['dev']:3s} {float(r['L_m'])*1e6:6.2f} {float(r['Vds']):4.1f} "
              f"{float(r['Vsb']):3.1f} {float(r['Vgs']):5.2f} {r['id_err']*100:6.2f}% "
              f"{r['gm_err']*100:6.2f}% {r['vth_err_mV']:6.2f}mV {r['sg_err']*100:6.2f}% "
              f"{'PASS' if r['status'] == 'pass' else 'FAIL'}")
    if b:
        print("\n" + "=" * 78)
        print(f"B 档（反解抽检）：{len(b_ok)}/{len(b)} 通过")
        print("=" * 78)
        for r in b:
            if r.get("status") == "missing_raw":
                print(f"{r['name']}: 缺原始结果")
                continue
            print(f"{r['name']:6s} {r['dev']:2s} L={float(r['L_m'])*1e6:.2f}µm "
                  f"W={float(r['W_um']):.2f}µm Vgs={float(r['Vgs']):.3f}V  "
                  f"gm/Id 目标 {float(r['gmid_target']):.2f} 实测 {r['gmid_sim']:.2f} "
                  f"({r['gmid_err']*100:.2f}%)  id {r['id_err']*100:.2f}%  "
                  f"{'PASS' if r['status'] == 'pass' else 'FAIL'}")

    lines = ["# LUT × Spectre 点抽样验证（05.3/05.6 补充）", "",
             f"- 生成时间：2026-11-25", f"- 判据：A 档 id≤1%、gm≤3%、vth≤5 mV、SG≤5%；B 档 gm/Id≤3%、id≤5%",
             "", "## A 档（点数抽样复核表本身）", "",
             "| 点 | dev | L (µm) | Vds | Vsb | Vgs | id 误差 | gm 误差 | vth 误差 | SG 误差 | 状态 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in a:
        if r.get("status") == "missing_raw":
            lines.append(f"| {r['name']} | {r['dev']} | - | - | - | - | - | - | - | - | 缺结果 |")
        else:
            lines.append(f"| {r['name']} | {r['dev']} | {float(r['L_m'])*1e6:.2f} | {float(r['Vds']):.1f} | "
                         f"{float(r['Vsb']):.1f} | {float(r['Vgs']):.2f} | {r['id_err']*100:.2f}% | "
                         f"{r['gm_err']*100:.2f}% | {r['vth_err_mV']:.2f} mV | {r['sg_err']*100:.2f}% | "
                         f"{'✅' if r['status'] == 'pass' else '❌'} |")
    lines += ["", f"**通过 {len(a_ok)}/{len(a)}**。", "", "## B 档（反解端到端抽检）", ""]
    if b:
        lines += ["| 设计 | dev | L (µm) | W (µm) | Vgs | gm/Id 目标 | gm/Id 实测 | 误差 | id 误差 | 状态 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in b:
            if r.get("status") == "missing_raw":
                lines.append(f"| {r.get('design')} | {r['dev']} | - | - | - | - | - | - | - | 缺结果 |")
            else:
                lines.append(f"| {r.get('design')} | {r['dev']} | {float(r['L_m'])*1e6:.2f} | "
                             f"{float(r['W_um']):.2f} | {float(r['Vgs']):.3f} | "
                             f"{float(r['gmid_target']):.2f} | {r['gmid_sim']:.2f} | "
                             f"{r['gmid_err']*100:.2f}% | {r['id_err']*100:.2f}% | "
                             f"{'✅' if r['status'] == 'pass' else '❌'} |")
        lines += ["", f"**通过 {len(b_ok)}/{len(b)}**。"]
    lines += ["", "## 方法", "",
              "- 抽点：从 `gmid_table.csv` 随机抽（固定种子），n/p 各半，覆盖不同 L/Vds/Vsb/Vgs；",
              "- deck：单管 + 固定工作点 + `dc`，与上游 `diag.scs` 同一个 PDK/温度/容差设置；",
              "- 执行：`ssh ic618` 在 VM 里跑 Spectre 18.1，结果 psfascii 回传后本地解析；",
              "- B 档尺寸来自 `tools/solve_lw.py` 的反解结果（M1/M6）。", "",
              "## 文件", "", "- `points.csv` 抽点清单", "- `decks/` 单点 deck",
              "- `raws/` VM 回传的原始输出", "- `results.csv` 逐点比对", ""]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告：{out / 'README.md'}")
    return 0 if (len(a) and len(a_ok) == len(a) and len(b_ok) == len(b)) else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="LUT × Spectre 点抽样验证")
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--lut", type=Path, default=DEFAULT_LUT)
    ap.add_argument("--sizing", type=Path, default=DEFAULT_SIZING)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "2026-11-25-lut-spotcheck")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.gen:
        return gen(a.lut, a.sizing, a.out, a.n, a.seed)
    if a.parse:
        return parse(a.out, a.lut)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))