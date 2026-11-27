#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从源设计网表提取"第一约束条件表"：逐管工作点（Id/gm/gds/self_gain 等）。

做法：
  1. 读取源网表（如 runs/2026-11-25-io18-ac/src_net.scs），追加 save 语句；
  2. 送 VM 跑一次 op（Spectre），回传 op 结果；
  3. 解析逐管 ids/gm/gds/vth/vdsat/vgs/vds，结合网表里的 w/l/fingers，
     输出 constraints.csv / constraints.json。

用法：
  python tools/source_constraints.py --net runs/2026-11-25-io18-ac/src_net.scs
"""
from __future__ import annotations

import argparse
import csv
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
DEV_RE = re.compile(r'^\s*(M\w+)\s*\(([^)]*)\)\s*(\w+)(.*)$')
PARAM_RE = re.compile(r'(\w+)=([-\d.eE+uUmMkKnNpPfF]+)')
NAME_RE = re.compile(r'^"([^"]+)"(?:\s+"([^"]*)")?\s+([-\d.eE+]+)')


def ssh(cmd: str, timeout: int = 180) -> tuple[int, str]:
    p = subprocess.run(["ssh", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=8", SSH, cmd],
                       capture_output=True, text=True, timeout=timeout, **SUBKW)
    return p.returncode, (p.stdout or "") + ("\n" + (p.stderr or "") if p.returncode else "")


def parse_netlist(path: Path) -> dict:
    devs = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = DEV_RE.match(line.strip())
        if not m:
            continue
        name, terms, master, rest = m.group(1), m.group(2).split(), m.group(3), m.group(4)
        params = {k.lower(): v for k, v in PARAM_RE.findall(rest)}
        devs[name] = {"terms": terms, "master": master, "params": params}
    return devs


def parse_op(path: Path) -> dict:
    out: dict[str, float] = {}
    in_value = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s == "VALUE":
            in_value = True
            continue
        if not in_value or not s.startswith('"'):
            continue
        m = NAME_RE.match(s)
        if m:
            try:
                out[m.group(1)] = float(m.group(3))
            except ValueError:
                pass
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "2026-11-27-generic" / "constraints")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    net = a.net.read_text(encoding="utf-8", errors="replace")
    if "save *:ids" not in net:
        net = net.replace("save OUT", "save OUT *:ids *:gm *:gds *:vth *:vdsat *:vgs *:vds\nsave", 1)
        if "save *:ids" not in net:  # 没有 save 行则追加在 op 分析前
            net = net.replace("op1 dc", "save *:ids *:gm *:gds *:vth *:vdsat *:vgs *:vds\nop1 dc")
    if "saveOptions options save=allpub" not in net:
        net = net.replace("op1 dc", "saveOptions options save=allpub\nop1 dc")
    deck = a.out / "src_op.scs"
    deck.write_text(net, encoding="utf-8", newline="\n")

    remote = "/tmp/src-constraints"
    subprocess.run(["ssh", SSH, f"rm -rf {remote} && mkdir -p {remote}"], check=True, **SUBKW)
    subprocess.run(["scp", str(deck), f"{SSH}:{remote}/net.scs"], check=True, **SUBKW)
    rc, out = ssh(f"cd {remote} && timeout 180 /opt/eda/cadence/SPECTRE181/bin/spectre "
                  f"-f psfascii net.scs -raw raw > spectre.log 2>&1; echo EXIT=$?; tail -3 spectre.log")
    print(out.strip().splitlines()[-1] if out.strip() else "")
    subprocess.run(["scp", "-r", f"{SSH}:{remote}/raw/op1.dc", str(a.out / "src_op.dc")],
                   check=True, **SUBKW)

    devs = parse_netlist(a.net)
    op = parse_op(a.out / "src_op.dc")
    rows = []
    for name, d in devs.items():
        prefix = f"{name}:"
        cand = {k: v for k, v in op.items() if k.startswith(prefix) or k.startswith("I0." + prefix)}
        get = lambda key: next((v for k, v in cand.items() if k.endswith(":" + key)), None)  # noqa: E731
        ids, gm, gds = get("ids"), get("gm"), get("gds")
        if ids is None or gm is None:
            continue
        ids, gm = abs(ids), abs(gm)
        gds = abs(gds) if gds else 1e-30
        w = d["params"].get("w", "")
        l = d["params"].get("l", "")
        rows.append({
            "inst": name, "master": d["master"], "pol": "n" if d["master"].lower().startswith("n") else "p",
            "w": w, "l": l, "fingers": d["params"].get("fingers", "1"),
            "id": ids, "gm": gm, "gds": gds,
            "gmoverid": gm / ids if ids else 0.0,
            "self_gain": gm / gds,
            "vgs": get("vgs") or 0.0, "vds": get("vds") or 0.0, "vsb": get("vsb") or 0.0,
            "vth": get("vth") or 0.0, "vdsat": get("vdsat") or 0.0,
        })
    if not rows:
        print("❌ 没解析到器件工作点（检查 save 是否生效）")
        return 1
    csv_path = a.out / "constraints.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (a.out / "constraints.json").write_text(
        json.dumps({"design": a.net.stem, "netlist": str(a.net), "devices": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ {len(rows)} 个器件 → {csv_path}")
    for r in rows:
        print(f"  {r['inst']:4s} {r['master']:10s} Id={r['id']*1e6:8.1f}uA gm={r['gm']*1e3:7.3f}mS "
              f"gm/Id={r['gmoverid']:5.1f} Aint={r['self_gain']:8.1f} ({20*__import__('math').log10(r['self_gain']):.1f}dB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))