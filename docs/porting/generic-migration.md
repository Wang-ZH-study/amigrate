# 通用化迁移：任意 PDK 的自动建表与尺寸反解（2026-11-27）

> 目标：目标 PDK 不再写死在代码里，而是"发现 PDK → 生成该 PDK 的器件表 → 用源设计约束查表 → 反解尺寸 → 交给 SKILL 换器件/写尺寸"。

## 1. 流程与模块

```
目标 PDK 目录名
   │
   ├─① tools/pdk_discover.py        扫描 Tech/<PDK>：模型文件、section 工艺角、四端 MOS、失配参数
   │        → runs/<date>/discover/<PDK>.json
   ├─② tools/build_lut_generic.py   按发现配置生成 DC 扫描 deck → VM 跑 Spectre → LUT CSV
   │        → runs/<date>/lut/lut_<PDK>.csv（列与迁移版表一致）
   ├─③ tools/source_constraints.py  源设计网表跑 op → 逐管 Id/gm/gds/Vgs/Vds/self_gain
   │        → runs/<date>/constraints/constraints.csv（"第一约束条件表"）
   ├─④ tools/solve_generic.py       目标表 × 约束 → 每管 W/L（保 gm/Id 与 self_gain）
   │        → sizes.csv + conv.config + generic_convert.il
   └─⑤ tools/generic_flow.py        串联 ①–④，输出 summary.json / README.md
```

网页版：`通用迁移（其他 PDK）` 卡片 → 选择/输入目标 PDK → 后台跑上述流程，进度按 `STAGE n/5` 实时显示。

## 2. 关键口径

- **器件发现是启发式**：找 `section` 文件 + `inline subckt`/`model` 四端器件；n/p 按名字首字母；电压档从名字（n33→3.3V、n12→1.2V）推断，并用 VDD 截断。
- **建表网格**：`Ls`、`Vds`、`Vsb`、`Vgs step` 全在发现 JSON 里，可改；代价是 deck 数 × 每 deck 时间。
- **尺寸求解**：目标表 W 归一化 10µm；选 (L,Vds,Vsb,gm/Id) 最接近源器件的行，再 `W = 10µm × Id_src / id_row`，从而同时保持电流与 gm/Id；用 self_gain 残差 `|ln(Aint_row/Aint_src)|` 评估。
- **SKILL**：生成的 `generic_convert.il` 走已验证路径（`dbCopyCellView` → `abConvertComponentParams` → `dbReplaceProp w/l/fingers/m` → `schCheck/dbSave`）。

## 3. 已验证结果（2026-11-27）

- **发现**：13mmrf → 角文件 `ms013_io33_v2p6_7p_spe.lib`，角 `tt/ff/ss/fnsp/snfp`，器件候选 `n12/n33/p12/p33_mis_ckt`；TSMC-65nm → `nch_rf/pch_rf`；CSMC_18 没有 Spectre 模型（只有 cdb/Subcircuit），会明确报"未找到"。
- **建表**：13mmrf pilot（2 器件 × 10 Vgs 点）→ 20 行，id/gm/self_gain 物理合理（例：n33 L=0.5µm Vgs=1.0V → Id 219µA、gm 1.03mS、Aint 37）。
- **约束提取**：源 OPA_D 8 个器件工作点全部拿到（例：M1 p18e2r Id 25.4µA、gm 0.228mS、gm/Id 9.0、Aint 189.5）。
- **反解**：8/8 器件求出尺寸（M1 22.15µm/L0.5µm、M7 78.5µm 等）；pilot 表网格太粗，残差 0.07–1.6，正式使用需按完整网格重跑建表。
- 网页接口实测：`POST /api/start {kind:"generic", quick:true}` → 8/8，输出 `runs/2026-11-26-webui/generic-<时间戳>/`。

## 4. 已知问题 / 下一步

1. **建表太慢**：13mmrf 的 `*_mis_ckt` 器件（含 statistics 块）单个 deck 约 3 分钟；全网格（多 L/Vds/Vsb）会到小时级。下一步：用非 mismatch 器件名做表（若 PDK 提供）、把 mismatch 参数单独从模型提取、或减少 Vgs 点数 + 并行度提高。
2. **器件选择**：自动挑的 n/p 不一定是目标电压档（如 1.2V vs 3.3V）；目前靠 `--devs` 覆盖，后续可在 UI 里列出候选让人选。
3. **R/C 映射**：当前 conv.config 只处理 MOS；源图用 analogLib 理想 R/C，暂不影响仿真；版图级需补 `rhrpo/mim2_tm`。
4. **SKILL 未自动执行**：`generic_convert.il` 已生成，但网页流程停在"生成脚本"；下一步接 `wscript`/`virtuoso -nograph` 跑它并回读校验。
5. 建表网格/工艺角参数化（目前默认 tt + 少量 Vds/Vsb）。
## 5. VDD 可配置（2026-11-27）

**为什么需要**：目标 PDK 的电压域不固定（1.2V 核心 / 1.8V / 2.5V / 3.3V IO），VDD 会影响：

- 器件表里 p 管的 VDD 参考（`VDD-VDS`、`VDD-VGS`）；
- Vgs 扫描上限：`vgs_max = min(器件耐压, VDD)`；
- 后续验证网表的供电（PVT/AC 需同值）。

**怎么用**：

- CLI：`pdk_discover.py --vdd 1.2`、`generic_flow.py --vdd 1.2`；
- 网页版第 4 节：勾选「自定义 VDD」并填值（默认 1.8V，不勾则用 1.8V）；
- 桌面工具后续同步同样入口。

**注意**：

- VDD 改变后必须**重新发现 + 重新建表**；"快速验证"复用旧表时 VDD 不生效，流程会打印警告；
- 源设计的偏置约束（Id/gm/Aint）来自源网表，不随目标 VDD 变化；改 VDD 只改目标器件表与验证环境；
- 若 VDD 低于器件阈值/饱和余量，F0–F4 的电压余量判据会直接报不可行。
