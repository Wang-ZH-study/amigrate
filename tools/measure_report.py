#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 Spectre psfascii 测量输出提取 OPA_D 指标：功耗、ICMR/输出摆幅、SR/建立、PSRR、THD。

用法：python tools/measure_report.py runs/2026-11-25-io18-ac/meas
"""
from __future__ import annotations

import cmath
import math
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KV = re.compile(r'^"([^"]+)"(?:\s+"[^"]*")?\s+([-\d.eE+]+)\s*$')


def parse_psf(path: Path) -> tuple[list[float], dict[str, list[float]], int]:
    """返回 (sweep, signals, npoints)。支持 op（单点）与 dc/tran（多点）。"""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        start = lines.index("VALUE")
    except ValueError:
        return [], {}, 0
    sweep: list[float] = []
    sig: dict[str, list[float]] = {}
    key = None
    for line in lines[start + 1:]:
        if line.startswith("END"):
            break
        m = KV.match(line)
        if not m:
            continue
        name, val = m.group(1), float(m.group(2))
        if name in ("time", "dc"):
            sweep.append(val)
            key = None
        elif name == "sweep":
            sweep.append(val)
            key = None
        else:
            if not sweep:
                sweep.append(0.0)
                key = None
            sig.setdefault(name, []).append(val)
    n = len(sweep)
    sig = {k: v for k, v in sig.items() if len(v) == n}
    return sweep, sig, n


def parse_ac(path: Path) -> tuple[list[float], dict[str, list[complex]]]:
    """解析 psfascii AC：freq + 复数信号。"""
    freq: list[float] = []
    sig: dict[str, list[complex]] = {}
    fre = re.compile(r'^"freq"\s+([-\d.eE+]+)\s*$')
    val = re.compile(r'^"([^"]+)"\s+\(([-\d.eE+]+)\s+([-\d.eE+]+)\)\s*$')
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = fre.match(line)
        if m:
            freq.append(float(m.group(1)))
            continue
        m = val.match(line)
        if m:
            sig.setdefault(m.group(1), []).append(complex(float(m.group(2)), float(m.group(3))))
    return freq, sig


def report(meas_dir: Path) -> dict:
    r: dict = {}
    sweep, sig, _ = parse_psf(meas_dir / "op1.dc")
    if "Vdd:p" in sig:
        i_dd = abs(sig["Vdd:p"][0])
        r["power_mw"] = 1.8 * i_dd * 1e3
        r["idd_ua"] = i_dd * 1e6
    r["vout_op"] = sig.get("OUT", [None])[0]

    # ICMR / 输出摆幅（单位增益缓冲，误差 ≤5mV）
    sweep, sig, _ = parse_psf(meas_dir / "dc1.dc")
    if sweep and "OUT" in sig and "vinp" in sig:
        ok = [(v, o) for v, o in zip(sig["vinp"], sig["OUT"]) if abs(o - v) <= 5e-3]
        if ok:
            r["icmr_lo"], r["icmr_hi"] = ok[0][0], ok[-1][0]
            r["out_swing_lo"] = min(o for _, o in ok)
            r["out_swing_hi"] = max(o for _, o in ok)

    # SR / 建立（阶跃 0.9→1.4V，Cl=5p）
    sweep, sig, _ = parse_psf(meas_dir / "tran1.tran.tran")
    if sweep and "OUT" in sig:
        t, v = sweep, sig["OUT"]
        srp = 0.0
        srm = 0.0
        for i in range(1, len(t)):
            dv = v[i] - v[i - 1]
            dt = t[i] - t[i - 1]
            if dt > 0:
                if dv > 0:
                    srp = max(srp, dv / dt)
                else:
                    srm = max(srm, -dv / dt)
        r["srp_v_per_us"] = srp * 1e-6
        r["srm_v_per_us"] = srm * 1e-6
        # 建立：阶跃后 OUT 进入 1.4V±0.5mV 的时间（相对阶跃起点 200ns）
        settle = None
        for i, (tt, vv) in enumerate(zip(t, v)):
            if tt >= 200e-9 and abs(vv - 1.4) <= 0.5e-3:
                settle = (tt - 200e-9) * 1e9
                break
        r["settle_ns"] = settle

    # PSRR（VDD AC=1，开环 OUT；PSRR = -20log10|OUT/VDD|）
    ac_path = meas_dir / "psrr.ac"
    if ac_path.exists():
        freq, sigs = parse_ac(ac_path)
        out = sigs.get("OUT", [])
        if freq and out:
            psrr = {}
            for f in (1.0, 1e3, 1e5):
                # 找最近的频点
                idx = min(range(len(freq)), key=lambda i: abs(math.log10(freq[i] / f)))
                psrr[f] = -20 * math.log10(max(abs(out[idx]), 1e-30))
            r["psrr_1hz"] = psrr[1.0]
            r["psrr_1khz"] = psrr[1e3]
            r["psrr_100khz"] = psrr[1e5]

    # THD（缓冲，1kHz 正弦 0.3V 幅度；重采样到均匀网格后 FFT）
    sweep, sig, _ = parse_psf(meas_dir / "thd.tran")
    if sweep and "OUT" in sig:
        try:
            import numpy as np
            t = np.array(sweep)
            v = np.array(sig["OUT"])
            mask = t >= 1e-3          # 跳过前 1ms 建立（3 个周期）
            tt, vv = t[mask], v[mask]
            if len(tt) < 1000:
                raise ValueError("瞬态点太少，无法做 FFT")
            tu = np.linspace(tt[0], tt[-1], 4096)
            vu = np.interp(tu, tt, vv)
            dt = tu[1] - tu[0]
            win = np.hanning(len(vu))
            spec = np.abs(np.fft.rfft((vu - vu.mean()) * win))
            freqs = np.fft.rfftfreq(len(vu), dt)
            f0 = 1e3

            def peak(f):
                k = int(round(f / (freqs[1] - freqs[0])))
                lo, hi = max(1, k - 2), min(len(spec) - 1, k + 2)
                return max(spec[lo:hi + 1])

            amp0 = peak(f0)
            harm = [peak(f0 * h) for h in range(2, 11) if f0 * h < freqs[-1]]
            thd = math.sqrt(sum(h * h for h in harm)) / amp0 * 100
            r["thd_pct"] = thd
        except Exception as e:  # noqa: BLE001
            r["thd_err"] = str(e)
    return r


def main(argv: list[str]) -> int:
    meas_dir = Path(argv[0]) if argv else Path("runs/2026-11-25-io18-ac/meas")
    r = report(meas_dir)
    print(f"{'参数':<18}{'值':>14}")
    print("-" * 34)
    if "power_mw" in r:
        print(f"{'静态功耗':<18}{r['power_mw']:>10.3f} mW   (Idd={r['idd_ua']:.1f}µA)")
    print(f"{'Vout 静态':<18}{(r.get('vout_op') or 0):>10.4f} V")
    if "icmr_lo" in r:
        print(f"{'输入共模范围':<18}{r['icmr_lo']:>7.2f}–{r['icmr_hi']:.2f} V")
        print(f"{'输出摆幅':<18}{r['out_swing_lo']:>7.2f}–{r['out_swing_hi']:.2f} V")
    if "srp_v_per_us" in r:
        print(f"{'SR+ (上升)':<18}{r['srp_v_per_us']:>10.1f} V/µs")
        print(f"{'SR- (下降)':<18}{r['srm_v_per_us']:>10.1f} V/µs")
    if r.get("settle_ns") is not None:
        print(f"{'建立(0.1%)':<18}{r['settle_ns']:>10.0f} ns")
    if "psrr_1hz" in r:
        print(f"{'PSRR @1Hz':<18}{r['psrr_1hz']:>10.1f} dB")
        print(f"{'PSRR @1kHz':<18}{r['psrr_1khz']:>10.1f} dB")
        print(f"{'PSRR @100kHz':<18}{r['psrr_100khz']:>10.1f} dB")
    if "thd_pct" in r:
        print(f"{'THD (0.3V@1k)':<18}{r['thd_pct']:>10.3f} %")
    elif "thd_err" in r:
        print(f"{'THD':<18}{'计算失败: ' + r['thd_err']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))