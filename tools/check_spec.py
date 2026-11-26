#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""迁移验收判卷脚本（零依赖，Python 3.11+ 自带 tomllib）。

三种用法：
  python tools/check_spec.py --check-spec            # 规格是否合法、证据是否齐全
  python tools/check_spec.py --judge <results.json>  # 用实测结果判 pass/fail
  python tools/check_spec.py --selftest              # 判卷逻辑自测

退出码：0 = 通过；1 = 未通过/缺项；2 = 规格或输入本身有问题。

设计原则（来自工单 03）：
  1. 缺数据必须报"缺项"，绝不能输出通过。
  2. out_of_scope 的层不得混进 pass。
  3. 判据全部来自 specs/migration-spec.toml，改容差不改代码。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "specs" / "migration-spec.toml"

REQUIRED_TOP = ("meta", "scope", "metrics", "corners", "statistics", "judging", "evidence")
REQUIRED_META = ("version", "design", "source_pdk", "source_baseline_run")
REQUIRED_METRIC = ("name", "unit", "direction", "status")


def load_spec(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def validate_spec(spec: dict) -> list[str]:
    """结构校验，返回错误列表。"""
    errs: list[str] = []
    for key in REQUIRED_TOP:
        if key not in spec:
            errs.append(f"缺少顶层段 [{key}]")
    if errs:
        return errs

    for key in REQUIRED_META:
        if key not in spec["meta"]:
            errs.append(f"[meta] 缺少字段 {key}")

    metrics = spec["metrics"]
    if not isinstance(metrics, list) or not metrics:
        errs.append("[[metrics]] 至少要有 1 条")
        metrics = []
    seen = set()
    for i, m in enumerate(metrics):
        for key in REQUIRED_METRIC:
            if key not in m:
                errs.append(f"[[metrics]] 第 {i + 1} 条缺少 {key}")
        name = m.get("name")
        if name in seen:
            errs.append(f"指标重名：{name}")
        seen.add(name)
        if m.get("direction") not in ("min", "max"):
            errs.append(f"{name}: direction 必须是 min 或 max")
        if m.get("status") not in ("active", "todo"):
            errs.append(f"{name}: status 必须是 active 或 todo")
        deg = m.get("allowed_relative_degradation")
        if not isinstance(deg, (int, float)) or not 0 <= deg < 1:
            errs.append(f"{name}: allowed_relative_degradation 应在 [0,1)")

    active = [m["name"] for m in metrics if m.get("status") == "active"]
    if not active:
        errs.append("没有任何 status=active 的指标，无法判卷")

    corners = spec["corners"]
    n_expected = len(corners.get("process", [])) * len(corners.get("voltage_scale", [])) * len(
        corners.get("temp_c", [])
    )
    if n_expected and n_expected != corners.get("points_expected"):
        errs.append(f"角集数量不一致：{n_expected} != points_expected={corners.get('points_expected')}")

    for layer in spec["scope"].get("layers_out_of_scope", []):
        if layer in spec["scope"].get("layers_covered", []):
            errs.append(f"{layer} 同时出现在覆盖与不覆盖清单里")

    if spec["judging"].get("out_of_scope_never_passes") is not True:
        errs.append("[judging] out_of_scope_never_passes 必须为 true")
    if spec["judging"].get("missing_evidence_is_failure") is not True:
        errs.append("[judging] missing_evidence_is_failure 必须为 true")
    return errs


def evidence_status(spec: dict) -> tuple[list[str], list[str]]:
    """返回 (已存在, 缺失) 两个证据路径列表（相对仓库根）。"""
    ok, missing = [], []
    for name, rel in spec.get("evidence", {}).items():
        p = ROOT / rel
        (ok if p.exists() else missing).append(f"{name}: {rel}")
    return ok, missing


def threshold(baseline: float, direction: str, deg: float) -> float:
    return baseline * (1 - deg) if direction == "min" else baseline * (1 + deg)


def judge(spec: dict, results: dict, baseline: dict) -> tuple[bool, list[dict], list[str]]:
    """返回 (是否通过, 明细行, 错误列表)。"""
    rows, errs = [], []
    bmetrics = baseline.get("metrics", baseline)
    rmetrics = results.get("metrics", results)

    for m in spec["metrics"]:
        name = m["name"]
        if m.get("status") != "active":
            rows.append({"metric": name, "state": "todo", "note": "未判（测试台未就绪）"})
            continue
        if name not in bmetrics:
            errs.append(f"源基线缺指标 {name}（{spec['meta']['source_baseline_run']}）")
            continue
        if name not in rmetrics:
            errs.append(f"实测结果缺指标 {name}")
            continue
        val = float(rmetrics[name])
        if name in bmetrics:
            base = float(bmetrics[name])
            th = threshold(base, m["direction"], float(m["allowed_relative_degradation"]))
        else:
            base = None
            th = None
        # 绝对下限/上限（用户给定最低目标）优先于相对基线
        abs_min = m.get("abs_min")
        abs_max = m.get("abs_max")
        if m["direction"] == "min" and abs_min is not None:
            th = float(abs_min) if th is None else max(th, float(abs_min))
        if m["direction"] == "max" and abs_max is not None:
            th = float(abs_max) if th is None else min(th, float(abs_max))
        if th is None:
            errs.append(f"{name}: 既无源基线也无绝对目标，无法判定")
            continue
        ok = val >= th if m["direction"] == "min" else val <= th
        rows.append(
            {
                "metric": name,
                "state": "pass" if ok else "fail",
                "baseline": base,
                "value": val,
                "threshold": th,
                "unit": m.get("unit", ""),
            }
        )

    # 角集完整性
    if spec["judging"].get("require_all_corners"):
        got = results.get("corner_count")
        want = spec["corners"]["points_expected"]
        if got is None:
            errs.append("结果缺 corner_count，无法确认 PVT 角集是否跑全")
        elif int(got) < want:
            errs.append(f"PVT 角集不全：{got}/{want}")

    passed = not errs and all(r["state"] == "pass" for r in rows if r["state"] != "todo")
    return passed, rows, errs


def print_report(spec: dict, ok_ev: list[str], missing_ev: list[str], errs: list[str]) -> None:
    print("=" * 72)
    print(f"迁移验收规格 v{spec['meta'].get('version')} — {spec['meta'].get('design')} "
          f"({spec['meta'].get('source_pdk')} → {spec['meta'].get('target_pdk_primary')})")
    print("=" * 72)
    print(f"覆盖层：{', '.join(spec['scope']['layers_covered'])}")
    print(f"不覆盖：{', '.join(spec['scope']['layers_out_of_scope'])}")
    print(f"角集：{spec['corners']['points_expected']} 点 "
          f"({len(spec['corners']['process'])}×{len(spec['corners']['voltage_scale'])}"
          f"×{len(spec['corners']['temp_c'])})")
    active = [m["name"] for m in spec["metrics"] if m.get("status") == "active"]
    todo = [m["name"] for m in spec["metrics"] if m.get("status") == "todo"]
    print(f"判卷指标：{', '.join(active)}")
    print(f"未判指标：{', '.join(todo) or '无'}")
    if ok_ev:
        print(f"\n已有证据 {len(ok_ev)} 项：")
        for e in ok_ev:
            print(f"  ok   {e}")
    print(f"\n缺失证据 {len(missing_ev)} 项：")
    for e in missing_ev:
        print(f"  MISS {e}")
    if errs:
        print("\n规格/输入错误：")
        for e in errs:
            print(f"  ERR  {e}")


def cmd_check_spec(spec_path: Path) -> int:
    spec = load_spec(spec_path)
    errs = validate_spec(spec)
    ok_ev, missing_ev = evidence_status(spec)
    print_report(spec, ok_ev, missing_ev, errs)
    if errs:
        print("\n结论：规格不合法。")
        return 2
    if missing_ev:
        print("\n结论：证据不齐 —— 不能判为通过（缺项即失败）。")
        return 1
    print("\n结论：规格与证据齐备，可以进入判卷。")
    return 0


def cmd_judge(spec_path: Path, results_path: Path) -> int:
    spec = load_spec(spec_path)
    errs = validate_spec(spec)
    if errs:
        print_report(spec, [], [], errs)
        return 2

    baseline_path = ROOT / spec["meta"]["source_baseline_run"]
    if not baseline_path.exists():
        print(f"结论：缺源基线 {baseline_path}，无法判卷（缺项即失败）。")
        return 1
    with baseline_path.open(encoding="utf-8") as f:
        baseline = json.load(f)
    with results_path.open(encoding="utf-8") as f:
        results = json.load(f)

    passed, rows, judge_errs = judge(spec, results, baseline)
    print("=" * 72)
    print("指标判卷")
    print("=" * 72)
    print(f"{'metric':8s} {'state':6s} {'baseline':>10s} {'value':>10s} {'threshold':>10s}  unit")
    for r in rows:
        if r["state"] == "todo":
            print(f"{r['metric']:8s} {'todo':6s} {'-':>10s} {'-':>10s} {'-':>10s}  未判")
        else:
            print(f"{r['metric']:8s} {r['state']:6s} {r['baseline']:10.4g} {r['value']:10.4g} "
                  f"{r['threshold']:10.4g}  {r['unit']}")
    for e in judge_errs:
        print(f"ERR  {e}")
    if passed:
        print("\n结论：迁移通过（所有 active 指标在容差内、角集完整）。")
        return 0
    print("\n结论：迁移未通过（见上方 fail / ERR / 缺项）。")
    return 1


def cmd_judge_abs(spec_path: Path, results_path: Path) -> int:
    """只按绝对最低目标（abs_min/abs_max）判卷，不做基线/角集检查。

    用途：用户给定的最低目标验收（2026-11-25）；PVT 角集与相对劣化另由 --judge 判。
    """
    spec = load_spec(spec_path)
    errs = validate_spec(spec)
    if errs:
        print_report(spec, [], [], errs)
        return 2
    with results_path.open(encoding="utf-8") as f:
        results = json.load(f)
    rmetrics = results.get("metrics", results)

    rows = []
    for m in spec["metrics"]:
        name = m["name"]
        abs_min, abs_max = m.get("abs_min"), m.get("abs_max")
        if abs_min is None and abs_max is None:
            rows.append({"metric": name, "state": "skip", "threshold": None, "value": None,
                         "note": "无绝对目标"})
            continue
        if name not in rmetrics:
            rows.append({"metric": name, "state": "missing", "threshold": abs_min or abs_max,
                         "value": None, "unit": m.get("unit", "")})
            continue
        val = float(rmetrics[name])
        th = float(abs_min) if abs_min is not None else float(abs_max)
        ok = val >= th if m["direction"] == "min" else val <= th
        rows.append({"metric": name, "state": "pass" if ok else "fail",
                     "threshold": th, "value": val, "unit": m.get("unit", "")})

    print("=" * 72)
    print("最低目标判卷（绝对阈值，不看源基线/角集）")
    print("=" * 72)
    print(f"{'metric':10s}{'state':8s}{'value':>10s}{'target':>10s}  unit")
    for r in rows:
        if r["state"] in ("pass", "fail"):
            print(f"{r['metric']:10s}{r['state']:8s}{r['value']:10.4g}{r['threshold']:10.4g}  {r['unit']}")
        else:
            print(f"{r['metric']:10s}{r['state']:8s}{'-':>10s}{'-':>10s}  {r.get('note', '')}")
    missing = [r["metric"] for r in rows if r["state"] in ("missing", "fail")]
    print("\n结论：" + ("最低目标全部通过。" if not missing else f"未通过：{missing}"))
    return 0 if not missing else 1


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def cmd_selftest() -> int:
    """用临时数据验证：达标判过、劣化判不过、缺指标判不过。"""
    spec = load_spec(DEFAULT_SPEC)
    errs = validate_spec(spec)
    if errs:
        print("自测失败：规格本身不合法：", errs)
        return 2

    base = {"metrics": {"gain": 78.0, "gbw": 34.0, "pm": 67.0, "srp": 14.5, "srm": 14.5, "power": 368.0}}
    good = {"metrics": {"gain": 77.0, "gbw": 33.5, "pm": 66.0, "srp": 14.0, "srm": 14.0, "power": 380.0},
            "corner_count": 45}
    bad = {"metrics": {"gain": 60.0, "gbw": 20.0, "pm": 50.0, "srp": 5.0, "srm": 5.0, "power": 900.0},
           "corner_count": 45}
    missing = {"metrics": {"gain": 77.0}, "corner_count": 45}

    ok_good, _, errs_good = judge(spec, good, base)
    ok_bad, _, _ = judge(spec, bad, base)
    ok_missing, _, errs_missing = judge(spec, missing, base)
    missing_corners = judge(spec, {**good, "corner_count": 9}, base)[0]

    checks = [
        ("达标样本应通过", ok_good and not errs_good),
        ("全面劣化样本应不通过", not ok_bad),
        ("缺指标应不通过并报错", not ok_missing and bool(errs_missing)),
        ("角集不全应不通过", not missing_corners),
        ("空证据目录应报缺项", bool(evidence_status(spec)[1])),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("\n自测" + ("通过" if not failed else f"失败：{failed}"))
    return 0 if not failed else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="迁移验收判卷脚本")
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument("--check-spec", action="store_true")
    ap.add_argument("--judge", type=Path)
    ap.add_argument("--judge-abs", type=Path)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if not a.spec.exists():
        print(f"规格文件不存在：{a.spec}")
        return 2
    if a.selftest:
        return cmd_selftest()
    if a.judge:
        return cmd_judge(a.spec, a.judge)
    if a.judge_abs:
        return cmd_judge_abs(a.spec, a.judge_abs)
    return cmd_check_spec(a.spec)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))