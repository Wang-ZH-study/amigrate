# 证据速览（工单 02 交付物）

> 日期：2026-11-25 ｜ 用途：后续工单只读这一页就能知道"选哪条路线、判据是什么、工具怎么办"。
> 全文证据：[模拟电路迁移文献综述](../../research/analog-migration-literature.md)（40 条）、[WiCkeD SPT 现状](../../research/wicked-spt-state.md)、[SPT 可获得性](../../research/spt-obtainability.md)。

## 一句话结论

模拟电路迁移有**四条路线**：网表重定尺寸、拓扑转换、版图迁移、学习型。本项目 v0 走**网表重定尺寸 + 显式映射表**（MunEDA SPT 的方法学，不依赖它的 license）；迁移配对用**同厂跨节点迁移**（SMIC 180nm `smic18ee` → SMIC 130nm `PDK_13mmrf_1P6M_30k`；2026-11-25 由"同节点 smic18mmrf"修订而来），文献依据随之从同节点横向（WCAS 2015）改为跨节点重定尺寸（电子学报 2019 的 0.35→0.13/90、TNT 的 180→22）。

## 四问四答

### 1. 主流路线有哪几条？各自什么时候翻车

| 路线 | 代表 | 强项 | 失败模式 |
|---|---|---|---|
| **网表重定尺寸** | gm/Id 保真（电子学报 2019）、MunEDA 优化流程 | 不动拓扑、可解释、风险最低 | 目标 PDK 缺器件就无解；只保一阶指标，保不住寄生；在高压/BCD 上约束维度暴增 |
| **拓扑转换** | MunEDA IP-ESC 2009、华为 WO2023/159506 | 能处理器件缺失，可利用新工艺红利 | 规则靠人写，无形式化等价判据；拓扑一改前面的 sizing 全废 |
| **版图迁移** | IPRAIL、Chameleon ART、GRAIN(ISEDA 2026)、ReLay | 保住对称/匹配/绕线等物理智能 | DRC/PDK 变化一大就崩；GRAIN 实测所选公开 baseline 全部 LVS 失败 |
| **学习型** | GCN-RL(DAC 2020)、迁移学习(ICECS 2025)、MigSizer(ICCD 2026) | 能复用跨工艺知识、省长尾劳动 | 无正确性保证、样本需求大、评价不可比；至今没有端到端迁移 + signoff 的公开结果 |

**结论**：学习型是增强项，不能当 v0 主线；**同厂跨节点（180→130）下，网表重定尺寸仍是风险最小的一条**，但要额外承担头寸重排与 1.2V/1.8V 供电方案——同节点横向（WCAS 2015）的证据不能直接搬用。

### 2. "迁移成功"怎么判

五层，缺一层就会拿"看起来能跑"当"迁移成功"：

1. **拓扑与工作点**：端口/极性/器件类别一致；逐管 Vgs/Vds/Id 与饱和区判定。
2. **物理检查**：ERC（悬空、多驱动、衬底/电压域）；DRC/LVS 若有版图才算。
3. **电气指标**：增益/GBW/PM/压摆率/功耗/失调/CMRR/PSRR/噪声，逐项给容差表。
4. **PVT + 统计**：完整角集 + 蒙卡或最坏情况距离（WCD），给良率/余量。
5. **PEX 后仿**：寄生态复测（本轮 out-of-scope，只留接口）。

判据写法参考：MunEDA 2015 的"每个样本在全工作范围满足规格才算成功"；AnalogGym 的统一 spec/仿真器/预算。**本项目把五层写进 `specs/`，机器可判。**

### 3. WiCkeD SPT 现在什么状态

- 2011-03-31 发布，当年 25,000 USD/年，宣称比手工快 10–100×（营销口径，无独立验证）。
- **2024 年被 Cadence 收购**；能力并入 Virtuoso Studio 的 **Custom Design Migration / Schematic Migration**（IC23.1/IC25.1），"SPT"是否仍是独立 SKU 存疑。
- 形态：**Virtuoso 内插件**，靠三张映射表（Cell/Property/Symbol）+ 分层遍历 + 自动重连；**只搬原理图，不做版图、不保证性能**。
- 获取：**无合法公开下载、无自助试用**；RHEL 6/7/8 + Virtuoso + 源/目标两套 PDK + license。详见 [可获得性调研](../../research/spt-obtainability.md)。

### 4. 我们借什么、不借什么

**借**：
- 借 **gm/Id 保真**（电子学报 2019）作映射的物理骨架；
- 借 **器件查找表 + DC 特征值约束**（华为 WO2023/159506 / CN116964587A）作工程实现；
- 借 **SPT 的三张映射表结构**（可 diff、可 review、可版本化）；
- 借 **跨节点重定尺寸**的公开先例（电子学报 2019：0.35→0.13/90 保 gm/Id；TNT：180→22 单管映射）；r1 后目标是 130nm，WCAS 2015 的同节点 bandgap 只能当旁证。

**不借**：
- 不借版图迁移（本轮不做，且 GRAIN 已证明公开 baseline 连 LVS 都过不了）；
- 不让 LLM 进收敛回路（没有端到端验证证据）；
- 不把"买了 SPT"当项目前置（拿不到就不做，是本末倒置）。

## 与上游第 7 周调研的关系（避免重复劳动）

`E:\IC-design-first\weeks_07_09\work\week_seven\02_调研报告_工艺迁移\` 已有一份 13 篇文献的调研，角度是**映射函数 $k_{tech}$ 的精度刻画**（研究型）。两者分工：

| | 上游第 7 周 | 本项目 auto-IC-move |
|---|---|---|
| 目标 | 提出并验证 $k_{tech}(g_m/I_D, L)$ 映射函数 | 把迁移**流程**跑通并验收；把 SPT 方法学落地 |
| 产出 | 映射函数精度、残差模型、对照实验 | 可复现迁移包、验收表、工具结论 |
| 关系 | 提供物理方法与文献底子 | 提供工程载体与验收口径 |

上游的 [04_可行性测绘](../../../IC-design-first/weeks_07_09/work/week_seven/02_调研报告_工艺迁移/04_可行性测绘_四个PDK.md) 特别有用：VM 里实测有 4 个 PDK（smic18ee、PDK_13mmrf、TSMC65 OA、CSMC18），且 130nm 有完整 Calibre DRC/LVS/xRC。

## 推荐阅读顺序（给人看）

| 顺序 | 读什么 | 为什么 |
|---|---|---|
| 1 | Silveira 等 1996，gm/ID 方法论（JSSC） | 一切映射的物理根基 |
| 2 | 于浩/郭裕顺/李康，《电子学报》2019, 47(8) | 中文、最贴近：保持 gm/Id 不变做 0.35µm→0.18/0.13/90nm 移植 |
| 3 | 华为 WO2023/159506（中文同族 CN116964587A） | 最可操作的工程流程：器件查找表 + DC 约束 + 失配 + 全仿真 |
| 4 | MunEDA IP-ESC 2009 + 2015 技术文 | SPT 方法学的原始表述：拓扑转换 + 优化 + PVT/蒙卡 |
| 5 | GRAIN (ISEDA 2026) + ReLay (arXiv 2611.25328) | 版图迁移与"版图↔生成器"的最新边界 |
| 6 | Papageorgiou (ICECS 2025)、GCN-RL (DAC 2020) | 学习型路线到底做到哪一步 |
| 附 | 上游 [02_文献综述](../../../IC-design-first/weeks_07_09/work/week_seven/02_调研报告_工艺迁移/02_文献综述_工艺迁移.md) | 13 篇 + 一张"路线×可解释性×样本需求"对照表，读起来更快 |

## 引用（速览里用到的关键链接）

- [Silveira 1996 gm/ID 方法论](https://iie.fing.edu.uy/publicaciones/1996/SFJ96/)
- [于浩等，电子学报 2019](https://doi.org/10.3969/j.issn.0372-2112.2019.08.004)
- [华为 WO2023/159506](https://patents.google.com/patent/WO2023159506A1/en) · [CN116964587A 全文](https://patentimages.storage.googleapis.com/81/2d/64/786840d6f2e515/CN116964587A.pdf)
- [MunEDA IP-ESC 2009](https://www.design-reuse.com/article/59496-analog-ip-porting-by-topology-conversion-and-optimization) · [WCAS 2015](https://www.muneda.com/pdf/publications/2015-09_New-Technology-Migration-Methodology-for-Analog-IC-Design.pdf)
- [GRAIN, ISEDA 2026](https://yibolin.com/publications/papers/ANALOG_ISEDA2026_Liu.pdf) · [ReLay, arXiv:2611.25328](https://arxiv.org/abs/2611.25328)
- [MunEDA 2011 发布稿](https://www.design-reuse.com/news/202519993-muneda-unveils-industry-s-first-commercially-available-automated-solution-for-process-technology-porting-of-circuit-schematics-and-ip/) · [Cadence WiCkeD 博客](https://www.design-reuse.com/blog/56179-a-deep-dive-into-ai-driven-optimization-with-wicked-the-optimization-powerhouse/)