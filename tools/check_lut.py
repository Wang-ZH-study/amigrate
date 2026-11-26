#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验迁移版器件 LUT 是否符合 specs/device-lut-schema.toml。

用法：
  python tools/check_lut.py --schema            # 只校验 schema 自身
  python tools/check_lut.py --check <lut.csv>   # 校验某张表

退出码：0 = 通过；1 = 表不符合 schema；2 = schema 或文件本身有问题。

设计原则：
  - 缺列 / 缺网格 / 重复键 / NaN 超阈值 → 一律非零退出（不静默通过）；
  - 网格外的点算错误（表的网格必须可比较），非必需列缺失只警告；
  - 与 specs/migration-spec.toml 的指标名做交叉校验，避免两套规格漂移。
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = ROOT / "specs" / "device-lut-schema.toml"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def validate_schema(schema: dict) -> list[str]:
    errs: list[str] = []
    for key in ("meta", "grid", "columns", "validation"):
        if key not in schema:
            errs.append(f"缺少顶层段 [{key}]")
    if errs:
        return errs

    g = schema["grid"]
    for key in ("dev", "L_um", "Vds_V", "Vsb_V", "Vgs_start_V", "Vgs_stop_V", "Vgs_step_V"):
        if key not in g:
            errs.append(f"[grid] 缺少 {key}")
    if not schema["meta"].get("normalization_w_um"):
        errs.append("[meta] 缺少 normalization_w_um")

    cols = schema["columns"]
    if not isinstance(cols, list) or not cols:
        errs.append("[[columns]] 至少要有 1 条")
        return errs
    names = set()
    for i, c in enumerate(cols):
        for key in ("name", "type", "required"):
            if key not in c:
                errs.append(f"[[columns]] 第 {i + 1} 条缺少 {key}")
        if c.get("type") not in ("str", "float", "int", "bool"):
            errs.append(f"{c.get('name')}: type 必须是 str/float/int/bool")
        if c.get("name") in names:
            errs.append(f"列重名：{c.get('name')}")
        names.add(c.get("name"))

    for key in schema["validation"].get("unique_key", []):
        if key not in names:
            errs.append(f"unique_key 里的 {key} 不在列定义里")

    spec_file = schema["meta"].get("spec_file")
    if spec_file and not (ROOT / spec_file).exists():
        errs.append(f"[meta] spec_file 不存在：{spec_file}")
    return errs


def parse_value(raw: str, typ: str):
    """返回 (值, 是否缺失)。解析失败抛 ValueError。"""
    s = (raw or "").strip()
    if s == "" or s.lower() in ("nan", "na", "n/a", "none", "null"):
        return None, True
    if typ == "str":
        return s, False
    if typ == "bool":
        low = s.lower()
        if low in ("true", "1", "yes", "t"):
            return True, False
        if low in ("false", "0", "no", "f"):
            return False, False
        raise ValueError(f"无法解析为 bool：{s}")
    if typ == "int":
        return int(float(s)), False
    v = float(s)
    if math.isnan(v) or math.isinf(v):
        return None, True
    return v, False


def check_table(schema: dict, path: Path) -> tuple[list[str], list[str], dict]:
    """返回 (错误, 警告, 统计)。"""
    errs: list[str] = []
    warns: list[str] = []
    stats: dict = {}

    cols = {c["name"]: c for c in schema["columns"]}
    required = [n for n, c in cols.items() if c.get("required")]

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)

    # L 列可能是米（1.8e-7）也可能是微米（0.18）：统一换算成 µm 再比网格
    l_scale = 1.0
    if "L" in header and rows:
        try:
            max_l = max(abs(float(r["L"])) for r in rows if r.get("L"))
            l_scale = 1e6 if 0 < max_l < 1e-3 else 1.0
        except ValueError:
            l_scale = 1.0

    stats["file"] = str(path)
    stats["rows"] = len(rows)
    if not rows:
        errs.append("表是空的")
        return errs, warns, stats

    missing_cols = [n for n in required if n not in header]
    extra_cols = [n for n in header if n not in cols]
    if missing_cols:
        errs.append("缺必需列：" + ", ".join(missing_cols))
    if extra_cols:
        warns.append("多出未定义列（将被忽略）：" + ", ".join(extra_cols))

    parsed_cols = [n for n in header if n in cols]
    nan_count = {n: 0 for n in parsed_cols}

    val = schema["validation"]
    uniq_key = val["unique_key"]
    seen = set()
    slices: dict[tuple, int] = {}
    bad_grid = 0
    non_sat = 0

    grid = schema["grid"]
    dev_set = set(grid["dev"])

    def off_grid(x: float, allowed) -> bool:
        return all(abs(x - a) > val["grid_rtol"] * max(1.0, abs(a)) for a in allowed)

    for i, row in enumerate(rows, start=2):
        record = {}
        for name in parsed_cols:
            try:
                v, miss = parse_value(row.get(name, ""), cols[name]["type"])
            except ValueError as e:
                errs.append(f"第 {i} 行 {name} 解析失败：{e}")
                continue
            if miss:
                nan_count[name] += 1
                continue
            record[name] = v
        if "dev" in record and record["dev"] not in dev_set:
            errs.append(f"第 {i} 行 dev={record['dev']} 不在网格 {sorted(dev_set)} 里")
        if "L" in record:
            record["L"] *= l_scale  # 统一为 µm
        for key, allowed in (("L", grid["L_um"]), ("Vds", grid["Vds_V"]), ("Vsb", grid["Vsb_V"])):
            if key in record and off_grid(record[key], allowed):
                bad_grid += 1
                if bad_grid <= 5:
                    errs.append(f"第 {i} 行 {key}={record[key]} 不在网格上")
        if "region" in record and int(record["region"]) != 2:
            non_sat += 1
        if all(k in record for k in uniq_key):
            key = tuple(record[k] for k in uniq_key)
            if key in seen:
                errs.append(f"第 {i} 行重复键 {key}")
            seen.add(key)
            skey = tuple(record[k] for k in uniq_key if k != "Vgs")
            slices[skey] = slices.get(skey, 0) + 1

    total = len(rows)
    for name in parsed_cols:
        frac = nan_count[name] / total
        if frac > val["max_nan_fraction"]:
            errs.append(f"列 {name} 缺失/NaN 比例 {frac:.1%} > {val['max_nan_fraction']:.0%}")

    expected = [(d, l, v, b) for d in grid["dev"] for l in grid["L_um"]
                for v in grid["Vds_V"] for b in grid["Vsb_V"]]
    stats["slices_expected"] = len(expected)
    stats["slices_present"] = len(slices)

    def close(a, b):
        return abs(a - b) <= val["grid_rtol"] * max(1.0, abs(b))

    missing_slices = []
    for (d, l, v, b) in expected:
        hit = [k for k in slices if k[0] == d and close(k[1], l) and close(k[2], v) and close(k[3], b)]
        if not hit:
            missing_slices.append((d, l, v, b))
    if missing_slices:
        preview = ", ".join(str(s) for s in missing_slices[:5])
        errs.append(f"缺 {len(missing_slices)} 个 (dev,L,Vds,Vsb) 切片，例如 {preview}")

    thin = [k for k, n in slices.items() if n < val["min_rows_per_slice"]]
    if thin:
        errs.append(f"有 {len(thin)} 个切片行数 < {val['min_rows_per_slice']}，例如 {thin[:3]}")

    if non_sat and not val["allow_non_sat"]:
        errs.append(f"schema 不允许非饱和行，但表里有 {non_sat} 行 region≠2")
    stats["non_sat_rows"] = non_sat

    # 与 migration-spec 指标名交叉校验（警告级）
    spec_file = schema["meta"].get("spec_file")
    if spec_file and (ROOT / spec_file).exists():
        spec = load_toml(ROOT / spec_file)
        spec_metrics = {m["name"] for m in spec.get("metrics", [])}
        for lut_col, metric in schema.get("metric_map", {}).items():
            if lut_col.startswith("note"):
                continue
            if metric not in spec_metrics:
                warns.append(f"metric_map: {lut_col} → {metric}，但 {spec_file} 里没有该指标")
            if lut_col not in header and lut_col != "noise_10k_file":
                warns.append(f"metric_map 引用的列 {lut_col} 不在表头里")

    return errs, warns, stats


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="迁移版器件 LUT 校验器")
    ap.add_argument("--schema", nargs="?", const=DEFAULT_SCHEMA, type=Path, default=DEFAULT_SCHEMA,
                    help="schema 路径（省略且不给 --check 时只校验 schema 自身）")
    ap.add_argument("--check", type=Path)
    ap.add_argument("--allow-partial", action="store_true", help="允许缺部分网格切片（仅建表中间态）")
    ap.add_argument("--skip-grid", action="store_true",
                    help="跳过网格覆盖检查（目标 PDK 的网格与 schema 不同时用，仅结构校验）")
    a = ap.parse_args(argv)

    if not a.schema.exists():
        print(f"schema 不存在：{a.schema}")
        return 2
    schema = load_toml(a.schema)
    schema_errs = validate_schema(schema)
    if schema_errs:
        print("schema 不合法：")
        for e in schema_errs:
            print("  ERR ", e)
        return 2
    if a.schema and not a.check:
        cols = len(schema["columns"])
        req = sum(1 for c in schema["columns"] if c.get("required"))
        print(f"schema OK：v{schema['meta']['version']}，{cols} 列（必需 {req}），"
              f"网格 {len(schema['grid']['dev'])}×{len(schema['grid']['L_um'])}×"
              f"{len(schema['grid']['Vds_V'])}×{len(schema['grid']['Vsb_V'])} 切片")
        return 0

    if not a.check.exists():
        print(f"表不存在：{a.check}")
        return 2

    errs, warns, stats = check_table(schema, a.check)
    if a.allow_partial or a.skip_grid:
        errs = [e for e in errs if not e.startswith("缺 ")]
        errs = [e for e in errs if "不在网格上" not in e]

    print("=" * 72)
    print(f"LUT 校验：{stats.get('file')}")
    print("=" * 72)
    print(f"行数 {stats.get('rows')}，切片 {stats.get('slices_present')}/{stats.get('slices_expected')}，"
          f"非饱和行 {stats.get('non_sat_rows')}")
    for w in warns:
        print("  WARN", w)
    if errs:
        print(f"\n发现 {len(errs)} 个问题：")
        for e in errs:
            print("  ERR ", e)
        print("\n结论：表不符合 schema。")
        return 1
    print("\n结论：表通过 schema 校验。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))