#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用化迁移主流程：发现 PDK → 建表 → 源约束 → 反解尺寸 → 生成 SKILL 脚本。

阶段（`STAGE i/5` 便于网页版解析进度）：
  1. 发现目标 PDK（pdk_discover.py）
  2. 构建目标器件表（build_lut_generic.py）
  3. 提取源设计约束（source_constraints.py）
  4. 通用反解尺寸（solve_generic.py）
  5. 汇总交付（plan.json + sizes.csv + conv.config + generic_convert.il）

用法：
  python tools/generic_flow.py --src-lib weekfour_last --src-cell OPA_D \
      --src-net runs/2026-11-25-io18-ac/src_net.scs --tgt-pdk PDK_13mmrf_1P6M_30k \
      --n-dev n33_mis_ckt --p-dev p33_mis_ckt --out runs/2026-11-27-generic/flow
  # 复用已有中间产物（跳过 1–3）：
  python tools/generic_flow.py --cfg ... --lut ... --constraints ... --out ...
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PY = sys.executable


def run(args: list[str], timeout: int = 3600) -> tuple[int, str]:
    print(f"[cmd] {' '.join(args)}", flush=True)
    p = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.splitlines()[-6:]:
        print("   " + line, flush=True)
    return p.returncode, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-lib", default="weekfour_last")
    ap.add_argument("--src-cell", default="OPA_D")
    ap.add_argument("--src-net", type=Path, default=ROOT / "runs/2026-11-25-io18-ac/src_net.scs")
    ap.add_argument("--tgt-pdk", default="PDK_13mmrf_1P6M_30k")
    ap.add_argument("--n-dev", default=None)
    ap.add_argument("--p-dev", default=None)
    ap.add_argument("--cfg", type=Path, default=None)
    ap.add_argument("--lut", type=Path, default=None)
    ap.add_argument("--constraints", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    out = Path(str(a.out).replace("\\", "/"))
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. 发现 PDK
    if a.cfg is None:
        print("STAGE 1/5 发现目标 PDK", flush=True)
        args = ["tools/pdk_discover.py", "--pdk", a.tgt_pdk, "--out", str(out / "discover")]
        if a.n_dev and a.p_dev:
            args += ["--devs", a.n_dev, a.p_dev]
        rc, _ = run(args)
        if rc != 0:
            print("❌ PDK 发现失败")
            return 1
        a.cfg = out / "discover" / f"{a.tgt_pdk}.json"

    cfg = json.loads(a.cfg.read_text(encoding="utf-8"))
    print(f"   器件：{cfg['devs']}，角：{cfg.get('corner')}", flush=True)

    # 2. 器件表
    if a.lut is None:
        print("STAGE 2/5 构建目标器件表（耗时较长）", flush=True)
        rc, _ = run(["tools/build_lut_generic.py", "--cfg", str(a.cfg),
                     "--out", str(out / "lut")])
        if rc != 0:
            print("❌ 建表失败")
            return 1
        a.lut = next((out / "lut").glob("lut_*.csv"))

    # 3. 源约束
    if a.constraints is None:
        print("STAGE 3/5 提取源设计约束", flush=True)
        rc, _ = run(["tools/source_constraints.py", "--net", str(a.src_net),
                     "--out", str(out / "constraints")])
        if rc != 0:
            print("❌ 源约束提取失败")
            return 1
        a.constraints = out / "constraints" / "constraints.csv"

    # 4. 反解尺寸
    print("STAGE 4/5 通用反解尺寸", flush=True)
    rc, _ = run(["tools/solve_generic.py", "--cfg", str(a.cfg), "--lut", str(a.lut),
                 "--constraints", str(a.constraints), "--out", str(out / "solve")])
    if rc != 0:
        print("❌ 反解失败")
        return 1

    # 5. 汇总
    print("STAGE 5/5 汇总交付物", flush=True)
    plan = json.loads((out / "solve" / "plan.json").read_text(encoding="utf-8"))
    ok = sum(1 for r in plan["rows"] if r.get("status") == "ok")
    summary = {
        "src": f"{a.src_lib}/{a.src_cell}",
        "src_net": str(a.src_net),
        "tgt_pdk": a.tgt_pdk,
        "cfg": str(a.cfg),
        "lut": str(a.lut),
        "constraints": str(a.constraints),
        "sizes": plan["sizes"],
        "skill": plan["skill"],
        "solved": f"{ok}/{len(plan['rows'])}",
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    lines = ["# 通用迁移流程结果", "",
             f"- 源：{summary['src']}", f"- 目标 PDK：{a.tgt_pdk}",
             f"- 器件表：{summary['lut']}", f"- 约束：{summary['constraints']}",
             f"- 尺寸：{summary['sizes']}（{summary['solved']} 个器件解出）",
             f"- SKILL：{summary['skill']}", f"- 用时：{summary['elapsed_s']} s", "",
             "> 说明：器件表网格越密、残差越小；当前为流程验证网格，正式使用请按 cfg 的完整网格重跑建表。", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"STAGE done {summary['solved']}，用时 {summary['elapsed_s']}s", flush=True)
    print(json.dumps({"out": str(out), "sizes": summary["sizes"], "skill": summary["skill"],
                      "solved": summary["solved"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))