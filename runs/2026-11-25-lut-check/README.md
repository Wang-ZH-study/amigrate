# 2026-11-25 LUT 校验器验证（05.1）

目的：证明 `tools/check_lut.py` 对"合规表"放行、对"坏表"逐类报错并非零退出。

## 命令

```bash
python tools/check_lut.py --schema                                   # schema 自身
python tools/check_lut.py --check runs/2026-11-25-lut-check/demo-lut-valid.csv
python tools/check_lut.py --check runs/2026-11-25-lut-check/demo-lut-bad.csv
python tools/check_lut.py --check "E:\IC-design-first\exchange\gmid\gmid_table.csv"   # 真实上游表
```

## 结果

| 输入 | 退出码 | 说明 |
|---|---|---|
| `--schema` | 0 | schema v1，30 列（必需 26），网格 2×9×4×5 = 360 切片 |
| `demo-lut-valid.csv` | 0 | 1800 行（每切片 5 点），360/360 切片，通过 |
| `demo-lut-bad.csv` | 1 | 5 类错误全报出：缺列 `inoise_10k`、L=0.25 不在网格、重复键、缺 352 切片、切片行数 < 5 |
| 上游 `gmid_table.csv` | 1 | 行数 15166、切片 360/360；缺 6 个迁移必需列（`inoise_1hz/inoise_10k/noise_src/avt/avt_src/is_sat`）→ 正确拒绝 |

## 说明

- `demo-*.csv` 是**合成数据**，只用于验证校验器行为，不代表任何真实工艺。
- 上游 `gmid_table.csv` 是"设计用"表：缺噪声/失配列、只留饱和行。迁移版表必须按 `specs/device-lut-schema.toml` 重建（工单 05.3/05.4）。
- 生成合成表的脚本是一次性内联命令，未入库；网格直接取自 schema。