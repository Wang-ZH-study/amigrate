#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用化尺寸反解：源约束表 + 目标 PDK 通用器件表 → 目标尺寸 + SKILL 转换脚本。

思路（与已验证流程一致）：
  - 对每个源器件，按极性选目标器件（cfg.devs）；
  - 在目标表里选 (L,Vds,Vsb) 最接近、gm/Id 最接近源器件的行；
  - 由 W = 10µm × Id_target / id_row 得到尺寸，使电流与 gm/Id 同时保持；
  - 校验：self_gain 不低于源器件、W/L 在可实现范围；
  - 输出 sizes.csv、conv.config、generic_convert.il（供 SKILL 复制/换器件/写尺寸）。

用法：
  python tools/solve_generic.py --cfg runs/.../PDK_13mmrf_1P6M_30k.json \
      --lut runs/.../lut.csv --constraints runs/.../constraints.csv --out runs/.../solve
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W_NORM_UM = 10.0
W_MIN, W_MAX = 0.5, 4000.0


def load_lut(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fv(r, k, default=float("nan")) -> float:
    v = r.get(k)
    if v in ("True", "False"):
        return 1.0 if v == "True" else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def pick_row(lut: list[dict], pol: str, L: float, vds: float, vsb: float, gmid: float):
    cand = [r for r in lut if r["dev"] == pol and fv(r, "is_sat") == 1.0]
    if not cand:
        return None

    def score(r):
        return (abs(math.log(max(fv(r, "L") * 1e6, 1e-6)) - math.log(max(L * 1e6, 1e-6))) * 3
                + abs(fv(r, "Vds") - vds) * 1.5 + abs(fv(r, "Vsb") - vsb)
                + abs(fv(r, "gmoverid") - gmid) * 0.35)
    return min(cand, key=score)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", type=Path, required=True)
    ap.add_argument("--lut", type=Path, required=True)
    ap.add_argument("--constraints", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "2026-11-27-generic" / "solve")
    a = ap.parse_args(argv)
    cfg = json.loads(a.cfg.read_text(encoding="utf-8"))
    lut = load_lut(a.lut)
    cons = list(csv.DictReader(a.constraints.open(encoding="utf-8-sig")))
    a.out.mkdir(parents=True, exist_ok=True)

    rows = []
    for c in cons:
        pol = c["pol"]
        dev = cfg["devs"][pol]
        Id = abs(float(c["id"]))
        gm_t = abs(float(c["gm"]))
        gmid_t = float(c["gmoverid"])
        L = float(c["l"].replace("u", "e-6").replace("n", "e-9")) if "u" in c["l"] or "n" in c["l"] else 0.5
        row = pick_row(lut, pol, L, abs(float(c["vds"])), abs(float(c["vsb"])), gmid_t)
        if row is None:
            rows.append({"inst": c["inst"], "status": "no_target_row"})
            continue
        id_row = abs(fv(row, "id"))
        gm_row = abs(fv(row, "gm"))
        w_um = W_NORM_UM * Id / id_row if id_row > 0 else 0.0
        gm_um = gm_row * w_um / W_NORM_UM
        status = "ok"
        if not (W_MIN <= w_um <= W_MAX):
            status = f"W_out_of_range({w_um:.1f})"
        Aint_t = float(c["self_gain"])
        Aint_row = fv(row, "self_gain")
        rows.append({
            "inst": c["inst"], "src_master": c["master"], "tgt_master": dev, "pol": pol,
            "W_um": round(w_um, 3), "L_um": round(fv(row, "L") * 1e6, 3),
            "fingers": 1,
            "Vgs": round(fv(row, "Vgs"), 4), "Vds": round(fv(row, "Vds"), 3), "Vsb": round(fv(row, "Vsb"), 3),
            "Id_uA": round(Id * 1e6, 2), "gm_mS": round(gm_um * 1e3, 3),
            "gmoverid": round(gm_um / Id, 2) if Id else 0,
            "Aint": round(Aint_row, 1), "Aint_target": round(Aint_t, 1),
            "residual": round(abs(math.log(max(Aint_row, 1e-9) / max(Aint_t, 1e-9))), 4),
            "status": status,
        })

    sizes = a.out / "sizes.csv"
    keys = ["inst", "src_master", "tgt_master", "pol", "W_um", "L_um", "fingers",
            "Vgs", "Vds", "Vsb", "Id_uA", "gm_mS", "gmoverid", "Aint", "Aint_target",
            "residual", "status"]
    with sizes.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    # conv.config：源 master → 目标 master（只写有尺寸的器件）
    src_masters = sorted({r["src_master"] for r in rows if r.get("status") == "ok"})
    conv_lines = ["# source_master target_cell target_master convert_params"]
    for m in src_masters:
        tgt = next(r for r in rows if r["src_master"] == m)["tgt_master"]
        conv_lines.append(f'{m} smic13mmrf_1233 {tgt} "w l fingers m"')
    (a.out / "conv.config").write_text("\n".join(conv_lines) + "\n", encoding="utf-8")

    # SKILL 脚本：复制 cellview → 换器件 → 写尺寸（与已验证 pilot7 流程一致）
    good = [r for r in rows if r.get("status") == "ok"]
    il = [
        ";; generic_convert.il —— 由 solve_generic.py 生成（源→目标 复制 + 换器件 + 写尺寸）",
        f'(setq src (dbOpenCellViewByType "{cfg.get("src_lib", "weekfour_last")}" '
        f'"{cfg.get("src_cell", "OPA_D")}" "schematic" "schematic" "r"))',
        '(setq dst (dbCopyCellView src "port_pilot" "OPA_D_generic" "schematic"))',
        '(setq dst (dbOpenCellViewByType "port_pilot" "OPA_D_generic" "schematic" "schematic" "a"))',
        f'(setq changed (abConvertComponentParams "{str(a.out / "conv.config").replace(chr(92), "/")}" dst))',
        "(foreach row (list",
    ]
    for r in good:
        il.append(f'  (list "{r["inst"]}" "{r["tgt_master"]}" {r["W_um"]:g} {r["L_um"]:g} {r["fingers"]})')
    il += [
        " )",
        "  (let (inst W L nf)",
        "    (setq inst nil)",
        "    (foreach i dst~>instances (when (equal i~>name (car row)) (setq inst i)))",
        "    (when inst",
        "      (setq W (cadr row) L (caddr row) nf (cadddr row))",
        '      (dbReplaceProp inst "w" \'string (sprintf nil "%.3fu" W))',
        '      (dbReplaceProp inst "l" \'string (sprintf nil "%.3fu" L))',
        '      (dbReplaceProp inst "fingers" \'string (sprintf nil "%d" nf))',
        '      (dbReplaceProp inst "m" \'string "1"))))',
        '(schCheck dst)',
        '(dbSave dst)',
        '(printf "generic convert done\\n")',
        "(exit)",
    ]
    il_path = a.out / "generic_convert.il"
    il_path.write_text("\n".join(il) + "\n", encoding="utf-8", newline="\n")

    plan = {"cfg": str(a.cfg), "lut": str(a.lut), "constraints": str(a.constraints),
            "sizes": str(sizes), "skill": str(il_path), "rows": rows}
    (a.out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"✅ {ok}/{len(rows)} 个器件求出尺寸 → {sizes}")
    for r in rows:
        if r.get("status") == "ok":
            print(f"  {r['inst']:4s} → {r['tgt_master']:12s} W={r['W_um']:9.2f}µm L={r['L_um']:.2f}µm "
                  f"gm/Id={r['gmoverid']:5.1f} Aint={r['Aint']:.0f} 残差={r['residual']:.3f}")
        else:
            print(f"  {r['inst']:4s} ⚠ {r['status']}")
    print(f"SKILL 脚本：{il_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))