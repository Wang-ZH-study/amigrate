# CMRR / PSRR / offset 角集结果（2026-11-26）

- 45 工况（5 process × 3 VDD × 3 temp），OPA_D v2（n33/p33 @1.8V）

| 指标 | 最小 | 最大 | 均值 |
|---|---|---|---|
| cmrr_db | 48.38 | 75.32 | 61.14 |
| psrr_db | -34.41 | 4.27 | -18.26 |
| offset_mv | -89.97 | 90.18 | 0.14 |

口径：CMRR=20log10(Ad/Acm)，Ad/Acm 取 1Hz 开环增益；PSRR=-20log10(|Vout/VDD|)；
offset 为单位增益缓冲下 Vout-0.9V（输入参考，mV）。

