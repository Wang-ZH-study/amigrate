# 迁移版 LUT 构建结果（05.3 / 05.4）

> 日期：2026-11-25 ｜ 工具：`tools/build_migration_lut.py` ｜ 判卷：`tools/check_lut.py`
> 两个 PDK 各扫一张"迁移版"表：保留全区域、补噪声与失配列、同一网格同一脚本。

## 1. 量

| PDK | 切片（dev×L×Vds×Vsb） | 行数（含 Vgs 扫描） | 非饱和行 | schema 校验 |
|---|---|---|---|---|
| smic18ee（源，180nm） | 360/360 | 32,760 | 17,594 | ✅ 通过（完整网格） |
| PDK_13mmrf（目标，130nm） | 360/360 | 24,120 | 13,150 | ✅ 通过（`--skip-grid`，130nm 的 L 网格与 180nm schema 不同） |

- 18ee：Vgs 0→1.8 V 步长 20 mV（91 点/切片）；13mmrf：Vgs 0→1.32 V（67 点/切片，1.2V core 器件上限）。
- 行数差异只来自 Vgs 点数：360×91=32,760；360×67=24,120。
- "非饱和行"大幅保留（18ee 17,594 / 13mmrf 13,150）——这正是迁移版表要的"全区域"，上游设计表把它们过滤掉了（32,760→15,166）。

## 2. 与上游表的逐点对照（源 PDK）

把重建表与 `gmid_table.csv` 在 15,166 个公共点上逐点比：

| 量 | 最大相对误差 |
|---|---|
| id | 5.0e-09 |
| gm | 4.9e-09 |
| vth | 1.2e-09 |
| gm/Id | 4.8e-09 |

**等价于逐点复现**（差异来自 die 尺寸常数 as/ad 的微小不同，可忽略）。这证明：
- 重建流程（deck 生成 → Spectre → psfascii 解析 → 归一化）没有引入系统误差；
- 上游表的值可信（与独立重建一致）。

## 3. 新增列怎么来的（诚实标注）

| 列 | 来源 | 状态 |
|---|---|---|
| `inoise_10k` | **推导**：热噪声 `sqrt(4kTγ/gm)`，γ=2/3 | ✅ 有值，`noise_src=derived` |
| `inoise_1hz` | **推导**：按 1/f 斜率 `inoise_1hz = 100×inoise_10k`（1 Hz vs 10 kHz 跨 4 个十倍频） | ✅ 有值，`noise_src=derived` |
| `avt` / `avt_src` | 13mmrf 有 `atox_n12/axl_n12` 失配参数；18ee 模型未暴露 AVT | ⏳ `avt=0`、`avt_src=pending`，**下游不得当真实失配用** |
| `Cgg/Cgd/Cdb_per_W` | Spectre oppoint 的 cgg/cgd/cdb ÷ W（10 µm），单位 fF/µm（与上游一致） | ✅ 与上游同点一致 |
| `is_sat` | 由 `region==2` 派生 | ✅ |

**噪声与失配是 v1 的近似**：真正做法是跑 Spectre noise 分析（输入参考噪声）和蒙卡拟合 AVT，已列入 05.3 的后续项；v1 表足以跑通反解/可行性，但 PVT/良率结论不能用它。

## 4. 产物

- `runs/2026-11-25-lut-build/smic18ee/lut_smic18ee.csv`、`decks/`（360 个 deck）
- `runs/2026-11-25-lut-build/13mmrf/lut_13mmrf.csv`、`decks/`
- `raws/` 未入库（体积大），可用同一命令重建

## 5. 重建命令

```bash
python tools/build_migration_lut.py --pdk smic18ee
python tools/build_migration_lut.py --pdk 13mmrf
python tools/check_lut.py --check runs/2026-11-25-lut-build/smic18ee/lut_smic18ee.csv
python tools/check_lut.py --check runs/2026-11-25-lut-build/13mmrf/lut_13mmrf.csv --skip-grid
```
## 6. 入库说明

两张完整表 **不入库**（18ee 12.1 MB / 13mmrf 8.9 MB，超过仓库体积约定），只保留本 README 与生成脚本：

- 表是**可重建产物**：`python tools/build_migration_lut.py --pdk smic18ee`（约 2–3 分钟，VM 内并行 6 路）；
- 校验命令见第 5 节；
- 若需要版本化快照，建议只提交"抽样 200 行"或按需生成，不提交全表。
