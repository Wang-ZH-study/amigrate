# LUT 从哪来、能不能用 VM 里的 Spectre 验

> 2026-11-25 ｜ 关联：工单 05.1/05.3/05.4/05.6
> 回答两个问题：**（1）LUT 是不是不用仿真就能"画"出来？（2）我给你的 LUT 能不能在 VM 里用 Spectre 验证？**

## 一、先把三种表分开，别混

| 表 | 是否存在 | 数据来源 | 能否用 Spectre 验证 |
|---|---|---|---|
| **合成 demo 表** `runs/2026-11-25-lut-check/demo-lut-valid.csv` | 已有 | 解析公式（平方律）生成，1800 行 | ❌ 无意义——它不是物理数据，只用来测校验器的放行/拦截行为 |
| **上游设计用表** `E:\IC-design-first\exchange\gmid\gmid_table.csv` | 已有 | **Spectre 实扫**（见下证据） | ✅ 可以，而且很有必要（验表 + 验插值链） |
| **迁移版两张表**（smic18ee / 13mmrf，按 `specs/device-lut-schema.toml`） | **还没有** | 必须重新用 Spectre 扫（工单 05.3/05.4） | ✅ 建完就要验（05.3 的验收标准） |

**结论 1：LUT 必须靠仿真建。** 我能不仿真做出来的只有：表结构（schema）、校验器、反解器、验证方案；**数据本身一行都造不出来**。之前给你看的 1800 行表是合成样本，只证明校验器能工作，不代表任何工艺。

## 二、上游表是仿真的证据链

- 扫描台：[`diag.scs`](E:\IC-design-first\exchange\gmid\diag\diag.scs)（`gmid_sweep.scs v2`）
  - 单管：`n18e2r` / `p18e2r`，W=10 µm，`m=1`，带 as/ad/ps/pd；
  - `include .../smic18ee_2P6M_20100810/models/spectre/e2r018_v1p8_spe.scs section=tt`；
  - `dc dc param=VGS start=0 stop=1.8 step=0.02`；VDS ∈ {0.2,0.5,0.9,1.4}，VSB ∈ {0,0.1,…,0.4}（体端独立偏置）。
- 运行记录：`exchange/gmid/run_*.log` 共 **216 个** = 9 个 L × 4 个 Vds × (1 组无 Vsb + 5 组 Vsb)，与网格一一对应；首行是 `Spectre (R) Circuit Simulator Version 18.1.0.077`。
- 原始输出：`gmid_raw.csv`（8.8 MB，逐点 DC 结果）→ 加工成 `gmid_table.csv`（15,166 行，滤掉非饱和行）。

所以 05.6 的 8/8 反解结果，验证的是"表 → 反解器"这一段；表本身是 Spectre 出来的，但**我还没有在 VM 里独立复算过**。

## 三、能用 VM 里的 Spectre 验证吗：能，三档方案

### A. 点抽样复核（验表本身）——首选，成本最低

从表里随机抽 20 个 `(dev, L, Vds, Vsb, Vgs)`，用改造版 `diag.scs` 逐点跑 DC，比较表值与 Spectre 值。

| 量 | 判据 |
|---|---|
| `id` | 相对误差 ≤ 1% |
| `gm` | 相对误差 ≤ 3% |
| `vth` | 绝对误差 ≤ 5 mV |
| `self_gain` | 相对误差 ≤ 5% |
| 噪声列（迁移表新增） | 1 Hz / 10 kHz 输入参考噪声 ≤ 10%，且 `noise_src=sim` |

**预期**：因为表就是从同一个 deck 扫出来的，同模型、同温度、同角下抽样点应该**几乎完全复现**（误差主要在 CSV 舍入与后处理）。如果抽样不过，说明表被二次加工坏了（例如单位、region 过滤、id/W 归一化出错）。

### B. 反解端到端抽检（验"表→反解→SPICE"闭环）——排除循环论证的关键

取 05.6 的两个管（输入对 M1 与尾电流 M5）：按反解器给出的 `(L, W, Vgs)` 建单管 Spectre 用例，量 `gm`、`id`，与"目标值"比较（判据：`gm/Id` 偏差 ≤ 3%，`id` ≤ 5%）。

这一步才真正证明"反解出来的尺寸在 SPICE 里也是那个工作点"，而不只是表内自洽。05.6 验收里的"2 管 SPICE 抽检"就是它。

### C. 重建切片交叉校验（验扫描台改造没改物理）

05.3 要用新版扫描台（加噪声、去 region 过滤）重扫。先挑 1 个切片（如 n/L=0.18/Vds=0.2/Vsb=0）用新台重跑，与旧表同点比 `gm`（判据 ≤ 1%）——证明"改台没改物理"，再全量扫。

## 四、为什么现在还没做

| 阻塞 | 说明 |
|---|---|
| 没有 Windows 版 Spectre | ✅ 已解决：VM 里有 Spectre 18.1（`/opt/eda/cadence/SPECTRE181/bin/spectre`） |
| VM 访问方式 | ✅ 已解决：Windows 上 `ssh ic618` 直连（配置见 [虚拟机SSH连接说明](../虚拟机SSH连接说明.md)），2026-11-25 17:13 实测连通 |
| 需要的动作 | 在 Windows 侧生成抽样清单与单点 deck，`scp`/共享目录送进 VM，`ssh ic618` 跑 Spectre，结果回传比对 |

**验证记录（2026-11-25 17:13，实测）**
- `ssh ic618 "hostname; whoami"` → `IC / IC`（192.168.233.128）；
- VM 内 PDK：`smic18ee_2P6M_20100810`、`PDK_13mmrf_1P6M_30k`、`TSMC-65nm(OA)`、`CSMC_18`；
- 共享目录：`/mnt/hgfs/IC-design-first`、`/mnt/hgfs/D`；
- Spectre 冒烟测试：把上游 `diag.scs` 拷到 `/tmp/ic-smoke` 跑一次 → **3.48 s，0 errors 0 warnings**，输出 `dc.dc`；
- 注意：VM 里 Python 是 **3.6.6**，跑不了用 `tomllib` 的脚本（3.11+）。所以**脚本在 Windows 跑，VM 只负责跑 Spectre**。

**仍待做**：抽样清单、单点 deck、回传比对。这些不需要额外授权，VM 通道已通。

## 六、验证结果（2026-11-25 17:35，已完成）

工装：`tools/lut_spotcheck.py`（`--gen` 抽点 + 生成 deck，`--parse` 解析 psfascii 并比对）。

| 档 | 内容 | 结果 |
|---|---|---|
| **A 档**（验表本身） | 从 `gmid_table.csv` 随机抽 20 点（n/p 各 10，覆盖不同 L/Vds/Vsb/Vgs），单管 deck 复算 | **20/20 通过**：id / gm / vth / self_gain 误差全部 **0.00%** |
| **B 档**（验反解闭环） | M1(p, L/W=0.5/4.16 µm)、M6(n, 0.5/10.32 µm) 按反解尺寸做单管抽检 | **2/2 通过**：gm/Id 12.57 → 12.48（0.66%）/ 12.55（0.10%）；id 偏差 1.30% / 0.34% |

**怎么解读这个 0.00%**：deck 与上游 `diag.scs` 用同一 PDK、同温度、同容差设置，等价于"同一台仪器复测同一批点"。所以它证明的是：
- 表的**数值、单位、归一化（W=10 µm）、取数**没有错；
- 我们读表/写 deck 的方式和上游一致。

它**不证明**插值精度——插值误差由 05.6 的"Vds 切片散布 10.5%"体现，那是 F4 判据要管的。

**证据**：`runs/2026-11-25-lut-spotcheck/`（`points.csv`、`decks/`、`raws/`、`results.csv`、`README.md`）。

## 五、下一步（按成本排序）

1. 生成抽样清单 `runs/<日期>-lut-spotcheck/points.csv`（20 点）+ 改造版扫描台（20 个单点 deck 或一个参数化 deck）；
2. 在 VM 跑 Spectre，回传结果；
3. 写 `tools/lut_spotcheck.py` 自动比对并出报告；
4. 通过后再做 05.3（全量重扫加噪声/失配）与 05.4（两张迁移表）。
## 8. 失配（avt）来源与口径（2026-11-26，与华为 CN116964587A 一致）

- 口径：**σ(ΔVt) = Avt / √(W·L)**（W、L 单位 µm，Avt 单位 mV·µm）；容忍带 **gm_target ∈ [gm_org, gm_org + 3σ]**。
- Avt 直接取 PDK 模型参数（不是拟合、不是抄文献）：

| 器件 | PDK 参数 | 值（V·µm） | 写入 LUT 的 avt（mV·µm） |
|---|---|---|---|
| n33 | vth_n33（ms013_io33_v2p6_7p_spe.lib） | 9.5e-3 | **9.5** |
| p33 | vth_p33 | 3.5e-3 | **3.5** |

- 写入方式：`tools/add_avt.py`（把 avt/avt_src 列刷进表，并在同目录生成 `avt-source.json` 记录出处）。
- 已刷表：`runs/2026-11-25-lut-build/13mmrf_io18/lut_13mmrf_io18.csv`（101,080 行全部 avt_src=model）。
- 求解端：`solve_lw.sigma_vt_mV` / `band_from_avt`；按平方律近似 Δgm/gm ≈ (gm/Id)·σ(ΔVt)/2，3σ 相对 gm 带 = 3·gmid·σ_vt/2。
- 示例（OPA_D v2 尺寸，3σ）：

| 管 | 器件 | W (µm) | L (µm) | σ(ΔVt) (mV) | 3σ (mV) | gm 带 ±% |
|---|---|---|---|---|---|---|
| M1/M2 | p33 | 244.2 | 0.5 | 0.32 | 0.95 | 0.60 |
| M3/M4 | n33 | 3.87 | 1.0 | 4.83 | 14.49 | 9.10 |
| M5/M8 | p33 | 15.77 | 0.5 | 1.25 | 3.74 | 2.35 |
| M6 | n33 | 42.9 | 1.0 | 1.45 | 4.35 | 2.73 |
| M7 | p33 | 87.43 | 0.5 | 0.53 | 1.59 | 1.00 |

- 注意：M3/M4 的 9.1% gm 带最大（面积最小），对应失配最敏感；蒙卡验证时优先看这几管。

## 9. β 失配（beta0/beta1）从模型提取（2026-11-26）

β ∝ µ·Cox·W/L，相对失配按模型参数合成：

    σ²(Δβ/β) ≈ du0² + (dtox/tox)² + (dxl/L)²
    du0      = au0 / √(W·L)          （W、L 用 µm）
    dtox/tox = (atox / √(W·L)) / tox
    dxl/L    = (axl / √W) / L

13mmrf 参数：au0=6e-4、atox(n)=4e-11/(p)=2.85e-11、axl(n)=3e-9/(p)=8e-10、tox=7e-9。
结果写入 LUT 的 beta0_low/high、beta1_low/high = 1 ∓ 3σ（来源 `beta-source.json`）。

| 器件 | 3σ 带宽（W=10/L=1） | （W=100/L=0.5） | （W=1/L=1） |
|---|---|---|---|
| n33 | 0.61% | 0.30% | 1.95% |
| p33 | 0.40% | 0.18% | 1.26% |

**结论**：默认 0.95/1.05（±5%）比模型给的带宽宽得多；大尺寸器件（如输入对 244µm）β 失配 <0.2%，小尺寸 M3/M4（3.87µm）约 1%。

## 10. 噪声：仿真结果（2026-11-26）

- 网表：`runs/2026-11-26-noise/opa_noise.scs`（OPA 开环，Vinp 为输入探针）、`dev_noise.scs`（单管 n33 W=10/L=1）。
- OPA_D v2 输入参考噪声：**1Hz 6.18µV/√Hz、10Hz 2.05µV、1kHz 232nV、10kHz 79.4nV、100kHz 28.7nV、1MHz 13.8nV**。
- 单管 n33：10kHz 94.6nV/√Hz、1MHz 15.1nV/√Hz；拟合 `N²(f)=A+B/f`：A=2.0e-16 V²/Hz（热噪声底 14.1nV/√Hz）、B=8.76e-11 V²·Hz。
- **重要**：表里 inoise 列是公式推导（仅 4kTγ/gm），比实测低 4–20 倍（未含 1/f 与偏置网络噪声）→ 不能用于噪声预算；要替换需按 `N²(f)=4kTγ/gm + Kf/(W·L)/f` 形式用本实验 Kf 拟合。
