#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""迁移版 LUT 的反解器：由源电路工作点反查目标器件的 (L, W)。

零依赖（只用标准库），只吃 CSV。

三个 API（工单 05.5）：
    solve_LW(lut, dev, target, vds, vsb, band=None) -> [Candidate]
    band_ok(lut, dev, L, W, target, band, vds, vsb) -> bool
    feasible(lut, dev, target, vds, vsb) -> Report

原理（与 docs/porting/lut-and-solver.md 一致）：
  1. 目标 gm/Id = gm_t / id_t —— 在 (dev, L, Vds, Vsb) 切片上按 gm/Id 插值解出 Vgs*；
  2. W = id_t / (id/W)|Vgs* —— 电流密度与 W 成反比；
  3. 回代校验（self_gain / gm 残差）；
  4. 单管解只是候选，必须再喂给电路级 DC 迭代。

用法：
  python tools/solve_lw.py --selftest
  python tools/solve_lw.py --lut <lut.csv> --dev n --id 11e-6 --gm 138e-6 --vds 0.5 --vsb 0
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOL = 1e-9
EPS = 1e-9


# ---------------------------------------------------------------- 基础工具
def close(a: float, b: float, rtol: float = 1e-6) -> bool:
    return abs(a - b) <= rtol * max(1.0, abs(a), abs(b))


def interp(xs: list[float], ys: list[float], x: float) -> float | None:
    """分段线性插值；x 超出范围返回 None。"""
    if not xs:
        return None
    if x < xs[0] - TOL or x > xs[-1] + TOL:
        return None
    if len(xs) == 1:
        return ys[0]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    if abs(x1 - x0) < TOL:
        return ys[lo]
    t = (x - x0) / (x1 - x0)
    return ys[lo] + t * (ys[hi] - ys[lo])


def crossings(xs: list[float], ys: list[float], target: float) -> list[float]:
    """找出 y(x)=target 的所有 x（线性插值），返回升序去重列表。"""
    out: list[float] = []
    for i in range(len(xs) - 1):
        y0, y1 = ys[i], ys[i + 1]
        if abs(y1 - y0) < TOL:
            if abs(y0 - target) < TOL:
                out.append(xs[i])
            continue
        if (y0 - target) * (y1 - target) <= 0:
            t = (target - y0) / (y1 - y0)
            out.append(xs[i] + t * (xs[i + 1] - xs[i]))
    uniq: list[float] = []
    for x in sorted(out):
        if not uniq or abs(x - uniq[-1]) > 1e-6:
            uniq.append(x)
    return uniq


def blend(s0: dict, s1: dict, t: float) -> dict:
    """两条 Vsb 切片按 t 线性混合（在 s0 的 Vgs 网格上重采样 s1）。"""
    out = {"vgs": s0["vgs"], "gmid": [], "idW_uAum": [], "self_gain": [], "vdsat": [],
           "gm": [], "id": [], "region": s0["region"]}
    for i, x in enumerate(s0["vgs"]):
        for arr in ("gmid", "idW_uAum", "self_gain", "vdsat", "gm", "id"):
            y1 = interp(s1["vgs"], s1[arr], x)
            if y1 is None:
                y1 = s0[arr][i]
            out[arr].append(s0[arr][i] * (1 - t) + y1 * t)
    return out


# ---------------------------------------------------------------- LUT
class Lut:
    """一张归一化器件表（W 固定，如 10 µm）。"""

    def __init__(self, rows: list[dict], w_norm_um: float = 10.0):
        self.w_norm_um = w_norm_um
        self.slices: dict[tuple, dict] = {}
        self.avt: dict[str, float] = {}
        self._build(rows)

    def _build(self, rows: list[dict]) -> None:
        # 统一 L 的单位为 µm：表里若用米（如 1.8e-7），这里换算一次
        max_l = max((abs(float(r["L"])) for r in rows), default=0.0)
        self.l_scale = 1e6 if 0 < max_l < 1e-3 else 1.0
        raw: dict[tuple, list[dict]] = {}
        for r in rows:
            key = (str(r["dev"]), float(r["L"]) * self.l_scale,
                   float(r["Vds"]), float(r["Vsb"]))
            raw.setdefault(key, []).append(r)
        for key, rs in raw.items():
            rs.sort(key=lambda r: float(r["Vgs"]))
            self.slices[key] = {
                "vgs": [float(r["Vgs"]) for r in rs],
                "gmid": [float(r["gmoverid"]) for r in rs],
                "idW_uAum": [float(r["id_W_uAum"]) for r in rs],
                "self_gain": [float(r["self_gain"]) for r in rs],
                "vdsat": [float(r.get("vdsat") or "nan") for r in rs],
                "gm": [float(r["gm"]) for r in rs],
                "id": [float(r["id"]) for r in rs],
                "region": [int(float(r["region"])) for r in rs],
            }
            first = rs[0]
            dev = str(first["dev"])
            if dev not in self.avt and first.get("avt") not in (None, "", "nan"):
                self.avt[dev] = float(first["avt"])

    # ---- 网格查询 ----
    def L_values(self, dev: str) -> list[float]:
        return sorted({k[1] for k in self.slices if k[0] == dev})

    def vds_values(self, dev: str) -> list[float]:
        return sorted({k[2] for k in self.slices if k[0] == dev})

    def vsb_values(self, dev: str) -> list[float]:
        return sorted({k[3] for k in self.slices if k[0] == dev})

    def slice_at(self, dev: str, L: float, vds: float, vsb: float) -> dict | None:
        """取 (dev, L, Vds) 下按 Vsb 插值后的切片；无数据返回 None。"""
        bases = [k for k in self.slices if k[0] == dev and close(k[1], L) and close(k[2], vds)]
        if not bases:
            return None
        for k in bases:
            if close(k[3], vsb):
                return self.slices[k]
        vss = sorted(k[3] for k in bases)
        lo = max((v for v in vss if v <= vsb), default=None)
        hi = min((v for v in vss if v >= vsb), default=None)
        if lo is None or hi is None:
            return None
        s0 = self.slices[next(k for k in bases if close(k[3], lo))]
        s1 = self.slices[next(k for k in bases if close(k[3], hi))]
        return blend(s0, s1, 0.0 if close(lo, hi) else (vsb - lo) / (hi - lo))


def sigma_vt_mV(lut: Lut, dev: str, w_um: float, l_um: float) -> float | None:
    """Pelgrom 模型：σ(ΔVt) = Avt / √(W·L)，W/L 单位 µm，Avt 单位 mV·µm。"""
    avt = lut.avt.get(dev)
    if avt is None or w_um <= 0 or l_um <= 0:
        return None
    return avt / math.sqrt(w_um * l_um)


def band_from_avt(lut: Lut, dev: str, w_um: float, l_um: float, gmid: float,
                  n_sigma: float = 3.0) -> dict | None:
    """华为 CN116964587A 的容忍带：gm_target ∈ [gm_org, gm_org + n·σ]。

    σ(ΔVt)=Avt/√(W·L)；按平方律近似 Δgm/gm ≈ (gm/Id)·σ(ΔVt)/2，
    故相对 gm 带 = n·gmid·σ_vt/2。
    """
    sv = sigma_vt_mV(lut, dev, w_um, l_um)
    if sv is None:
        return None
    rel = n_sigma * (gmid * sv * 1e-3) / 2.0
    return {"gm_rel": rel, "id_rel": rel, "sigma_vt_mV": sv, "n_sigma": n_sigma}


# ---------------------------------------------------------------- 反解
def solve_LW(lut: Lut, dev: str, target: dict, vds: float, vsb: float,
             band: dict | None = None) -> list[dict]:
    """给定目标 (id, gm[, self_gain]) 与工作点 (Vds, Vsb)，返回候选 [(L,W)]。"""
    id_t = float(target["id"])
    gm_t = float(target["gm"])
    if id_t <= 0 or gm_t <= 0:
        raise ValueError("id/gm 必须为正")
    gmid_t = gm_t / id_t
    sg_t = target.get("self_gain")

    cands: list[dict] = []
    for L in lut.L_values(dev):
        s = lut.slice_at(dev, L, vds, vsb)
        if s is None:
            continue
        for vgs in crossings(s["vgs"], s["gmid"], gmid_t):
            idW = interp(s["vgs"], s["idW_uAum"], vgs)
            sg = interp(s["vgs"], s["self_gain"], vgs)
            if idW is None or idW <= 0:
                continue
            w_um = id_t / (idW * 1e-6)
            if sg_t and sg:
                resid = abs(math.log(max(sg, 1e-12) / sg_t))
            else:
                resid = abs(gmid_t * id_t / gm_t - 1.0)
            cands.append({
                "dev": dev, "L_um": L, "W_um": w_um, "Vgs": vgs,
                "gmoverid": gmid_t, "self_gain": sg, "residual": resid,
            })
    cands.sort(key=lambda c: c["residual"])
    if band:
        cands = [c for c in cands if
                 band_ok(lut, dev, c["L_um"], c["W_um"], target, band, vds, vsb)] or cands
    return cands


def band_ok(lut: Lut, dev: str, L: float, W_um: float, target: dict,
            band: dict, vds: float, vsb: float) -> bool:
    """判断 (L,W) 处的实际 id/gm 是否落在容忍带内（带端点算通过）。"""
    s = lut.slice_at(dev, L, vds, vsb)
    if s is None or W_um <= 0:
        return False
    id_t = float(target["id"])
    gm_t = float(target["gm"])
    idW_need = id_t / (W_um * 1e-6)  # A/µm
    vgs_list = crossings(s["vgs"], s["idW_uAum"], idW_need)
    if not vgs_list:
        return False
    vgs = vgs_list[0]
    gmid = interp(s["vgs"], s["gmid"], vgs)
    idW = interp(s["vgs"], s["idW_uAum"], vgs)
    if gmid is None or idW is None:
        return False
    id_chk = idW * 1e-6 * W_um
    gm_chk = gmid * id_chk
    id_rel = abs(id_chk / id_t - 1.0)
    gm_rel = abs(gm_chk / gm_t - 1.0) if gm_t else 0.0
    return id_rel <= band.get("id_rel", 0.05) + EPS and gm_rel <= band.get("gm_rel", 0.05) + EPS


def feasible(lut: Lut, dev: str, target: dict, vds: float, vsb: float) -> dict:
    """目标 gm/Id 在该 (Vds,Vsb) 下是否可达；不可达给出 gap 与建议。"""
    gmid_t = float(target["gm"]) / float(target["id"])
    reach = []
    for L in lut.L_values(dev):
        s = lut.slice_at(dev, L, vds, vsb)
        if s is not None:
            reach.append((L, min(s["gmid"]), max(s["gmid"])))
    if not reach:
        return {"feasible": False, "gap_pct": None, "nearest": None,
                "advice": "该 (dev,Vds,Vsb) 在表里没有切片；检查网格或先建表"}
    cands = solve_LW(lut, dev, target, vds, vsb)
    if cands:
        best = cands[0]
        return {"feasible": True, "gap_pct": 0.0,
                "nearest": {"L_um": best["L_um"], "W_um": best["W_um"], "Vgs": best["Vgs"]},
                "advice": "可达；单管解需再进电路级 DC 迭代"}
    lo = min(r[1] for r in reach)
    hi = max(r[2] for r in reach)
    nearest = lo if abs(gmid_t - lo) < abs(gmid_t - hi) else hi
    gap = (gmid_t - nearest) / nearest * 100.0
    advice = "目标 gm/Id 偏高：增大 L 或提高电流密度要求" if gmid_t > hi else \
             "目标 gm/Id 偏低：减小 L 或接受更小的 gm/Id"
    return {"feasible": False, "gap_pct": gap, "nearest": {"gmoverid": nearest}, "advice": advice}


# ---------------------------------------------------------------- 自测
def _synth_lut() -> Lut:
    """解析表：饱和区平方律；self_gain 随 L 变化（否则 L 不可辨识）。"""
    k = 200e-6
    wn = 10.0
    rows = []
    for dev in ("n", "p"):
        for L in (0.18, 0.5, 1.0):
            sg_true = 20.0 + 0.3 / L          # 长沟道本征增益更高：L↑ → sg↑
            for vds in (0.2, 0.5, 0.9, 1.4):
                for vsb in (0.0, 0.1, 0.2, 0.3, 0.4):
                    vth = 0.45 + 0.05 * vsb
                    vgs = 0.40
                    while vgs <= 1.8001:
                        if vgs > vth:
                            id_a = 0.5 * k * (wn / L) * (vgs - vth) ** 2
                            gm = k * (wn / L) * (vgs - vth)
                            rows.append({
                                "dev": dev, "W": wn * 1e-6, "L": L * 1e-6,
                                "Vds": vds, "Vsb": vsb, "Vgs": vgs,
                                "id": id_a, "gm": gm, "gds": gm / sg_true,
                                "vth": vth, "vdsat": vgs - vth,
                                "gmoverid": gm / id_a, "self_gain": sg_true,
                                "region": 2, "vsat_marg": vds - (vgs - vth),
                                "id_W_uAum": id_a / wn * 1e6, "gain_dB": 20 * math.log10(sg_true),
                                "Cgg_per_W": 1e-10, "Cgd_per_W": 1e-11, "Cdb_per_W": 1e-11,
                            })
                        vgs += 0.02
    return Lut(rows, w_norm_um=wn)


def selftest() -> int:
    lut = _synth_lut()
    checks: list[tuple[str, bool]] = []

    # 1) 已知 (L, W, Vgs) → 反解回同一组 (L, W)，误差 < 1%
    #    表里行的 W 是归一化宽度（10 µm）；目标电流按 W_true/wn 缩放，才能验证 W 反解。
    L_true, W_true, vgs_true, vds_true = 0.5, 8.35, 0.9, 0.9
    s = lut.slice_at("n", L_true, vds_true, 0.0)
    id_row = interp(s["vgs"], s["id"], vgs_true)
    gm_row = interp(s["vgs"], s["gm"], vgs_true)
    sg_t = interp(s["vgs"], s["self_gain"], vgs_true)
    scale = W_true / lut.w_norm_um
    id_t, gm_t = id_row * scale, gm_row * scale
    cands = solve_LW(lut, "n", {"id": id_t, "gm": gm_t, "self_gain": sg_t}, vds_true, 0.0)
    best = cands[0]
    l_err = abs(best["L_um"] - L_true) / L_true
    w_err = abs(best["W_um"] - W_true) / W_true
    checks.append((f"反解回 (L,W)（真值 L={L_true} W={W_true}，解得 L={best['L_um']:.3f} "
                   f"W={best['W_um']:.3f}；误差 L {l_err:.2%} / W {w_err:.2%}）",
                   l_err < 0.01 and w_err < 0.01))

    # 2) 多 L 候选
    checks.append((f"多 L 候选（{len(cands)} 个）", len(cands) > 1))

    # 3) 不可达 gm/Id → feasible=False 而不是抛异常
    rep = feasible(lut, "n", {"id": 1e-5, "gm": 1e-5 * 500.0}, 0.9, 0.0)
    checks.append((f"不可达目标 feasible=False（gap={rep['gap_pct']:.1f}%）",
                   rep["feasible"] is False and rep["gap_pct"] is not None))

    # 4) 容忍带：带内通过、带外拒绝、边界（容差=0）通过
    in_band = band_ok(lut, "n", L_true, W_true, {"id": id_t, "gm": gm_t},
                      {"id_rel": 0.05, "gm_rel": 0.05}, vds_true, 0.0)
    out_band = band_ok(lut, "n", L_true, W_true * 1.5, {"id": id_t, "gm": gm_t},
                       {"id_rel": 0.05, "gm_rel": 0.05}, vds_true, 0.0)
    edge = band_ok(lut, "n", L_true, W_true, {"id": id_t, "gm": gm_t},
                   {"id_rel": 0.0, "gm_rel": 0.0}, vds_true, 0.0)
    checks.append(("容忍带：带内通过 / 带外拒绝 / 边界（容差 0）通过",
                   in_band and not out_band and edge))

    # 5) 极端输入不抛异常
    rep2 = feasible(lut, "n", {"id": 1e-5, "gm": 1e-12}, 0.9, 0.0)
    checks.append(("极小 gm/Id 不抛异常并给出建议", "advice" in rep2))

    for name, ok in checks:
        print(("  PASS  " if ok else "  FAIL  ") + name)
    ok_all = all(o for _, o in checks)
    print("\n自测" + ("通过" if ok_all else "失败"))
    return 0 if ok_all else 1


# ---------------------------------------------------------------- CLI
def load_lut(path: Path) -> Lut:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    wn = float(rows[0]["W"]) * 1e6 if rows else 10.0
    return Lut(rows, w_norm_um=wn)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="迁移 LUT 反解器")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--lut", type=Path)
    ap.add_argument("--dev", default="n")
    ap.add_argument("--id", dest="id_a", type=float)
    ap.add_argument("--gm", dest="gm_a", type=float)
    ap.add_argument("--vds", type=float, default=0.5)
    ap.add_argument("--vsb", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    if not a.lut or a.id_a is None or a.gm_a is None:
        ap.print_help()
        return 2
    lut = load_lut(a.lut)
    target = {"id": a.id_a, "gm": a.gm_a}
    cands = solve_LW(lut, a.dev, target, a.vds, a.vsb)
    rep = feasible(lut, a.dev, target, a.vds, a.vsb)
    if a.json:
        print(json.dumps({"candidates": cands[:10], "feasible": rep}, ensure_ascii=False, indent=2))
        return 0 if rep["feasible"] else 1
    print(f"目标 {a.dev} 管 id={a.id_a * 1e6:.3f} µA, gm={a.gm_a * 1e6:.3f} µS, "
          f"gm/Id={a.gm_a / a.id_a:.2f} 1/V @ Vds={a.vds} Vsb={a.vsb}")
    if not cands:
        print(f"不可行：gap={rep['gap_pct']:.1f}%  建议：{rep['advice']}")
        return 1
    print(f"{'L(µm)':>7} {'W(µm)':>10} {'Vgs(V)':>8} {'self_gain':>10} {'残差':>8}")
    for c in cands[:8]:
        print(f"{c['L_um']:7.2f} {c['W_um']:10.2f} {c['Vgs']:8.3f} {c['self_gain']:10.1f} {c['residual']:8.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))