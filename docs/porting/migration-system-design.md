# 从"流程"到"系统"：迁移工具链设计（对标 WiCkeD SPT）

> 2026-11-26 ｜ 回答两个问题：① 流程还差什么；② 能不能做成类似 WiCkeD Schematic Porting 的系统。

## 一、先看清 WiCkeD SPT 到底做什么

| 能力 | WiCkeD SPT（现 Cadence Schematic Migration） | 我们现在 |
|---|---|---|
| 读源原理图 | ✅ 原生（Virtuoso OA） | ✅ 通过 SKILL（07B 已验证 8/8 换器件） |
| 器件映射 | ✅ `conv.config`（cell/参数/公式） | ✅ `skill/conv.config`（MOS 已验证，R/C 未验证） |
| 改尺寸 | ❌ **不做**（只搬结构/参数，尺寸靠 designer 或 optiMOS） | ✅ **我们做了**（gm/Id + self_gain 反解，写入实例） |
| 重连引脚 | ❌ 不做（引脚数变化需人工） | ❌ 未处理 |
| 版图迁移 | ❌ 不做 | ❌ out-of-scope |
| 网表路径 | 无（依赖原理图） | ✅ 有（但网表是手写等价网表，未从原理图导出） |
| 验证 | 无（交给 ADE） | ✅ AC/瞬态/PVT/MC + 判卷脚本 |
| 目标 | 结构级"搬图" | 尺寸级"重定 + 验收" |

**结论：我们做的比 SPT 多（尺寸 + 验证），少的是"产品化"——CLI/工程文件/报告/可维护性。**

## 二、系统架构（6 个模块）

```
┌─────────────────────────────────────────────────────────────┐
│  CLI：amigrate init / table / solve / map / verify / report  │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ A. 器件表     │ B. 求解       │ C. 映射       │ D. 验证         │
│ table build  │ gm/Id+self   │ netlist +     │ AC/DC/TR/PVT/  │
│ + schema     │ gain + 3σ    │ schematic     │ MC + judge     │
│ + checker    │ + F0–F4      │ (SKILL/IL)    │                │
├──────────────┴──────────────┴──────────────┴────────────────┤
│ E. 工程/数据层：project.toml、device-map.toml、sizing.csv、   │
│    runs/<日期>-<主题>/、结果 result.json、报告生成            │
├─────────────────────────────────────────────────────────────┤
│ F. PDK 适配层：每个 PDK 一个 TOML（路径/器件名/参数名/角名/   │
│    Avt/β/模型 section），新增 PDK = 加一个配置文件           │
└─────────────────────────────────────────────────────────────┘
```

**关键设计原则**

1. **数据契约先行**：`sizing.csv`、`device-map.toml`、`result.json` 三类文件是模块间唯一接口（现在已有雏形）。
2. **PDK 适配层可插拔**：13mmrf/18ee 只是两个 TOML；加 PDK 不改代码。
3. **两个映射分支并存**：网表（快、可自动化）与原理图（可交付、需 Virtuoso）；同一尺寸表驱动两者。
4. **验收即代码**：`specs/*.toml` + `check_spec --judge/--judge-abs` 已是雏形，扩展成 PVT/MC 自动判卷。
5. **可复现**：每次操作落 `runs/<日期>-<主题>/`，报告从 run 目录生成，不许手填数字。

## 三、还差什么（按"变成系统"的必要性排序）

| # | 缺口 | 现状 | 工作量 | 优先级 |
|---|---|---|---|---|
| 1 | **原理图→网表导出** | AC/PVT/MC 用等价手写网表 | M（Virtuoso netlister 或 `hnlNetlist` 调用 + 网表 diff） | P0 |
| 2 | **噪声列实测刷新** | 公式低估 4–20× | S（Kf 已拟合，写脚本刷表） | P0 |
| 3 | **R/C 器件映射** | 只验证 MOS | M（`rhrpo`/`mime2r` 参数语义 + 换算函数） | P0 |
| 4 | 引脚重连检查 | 未做 | M（网表 diff + 引脚名/数量校验） | P1 |
| 5 | 完整统计蒙卡 | 只 Vt 失配 | M（接 PDK `sigma_mis_a–d`/统计块） | P1 |
| 6 | CMRR/offset/PSRR 角集 | 仅标称 | M（测试台 + 判据） | P1 |
| 7 | 工程文件/CLI | 一堆独立脚本 | M（argparse 统一 + project.toml） | P1 |
| 8 | 报告自动生成 | 手动写 Markdown/PPT | S–M（模板 + 数字注入） | P2 |
| 9 | 多电路支持 | 只 OPA_D | M（器件映射表与尺寸表参数化后自然支持） | P2 |
| 10 | GUI | 无 | L（可选；CLI+报告已够内部用） | P3 |

## 四、可行性判断

**可以做，而且不需要新物理/新算法**——缺的是软件工程工作量：

- 核心已具备：LUT 建表、反解、可行性、SKILL 映射、PVT/MC 验证、判卷；
- 难点在"最后一公里"：原理图导出（依赖 Virtuoso 环境）、R/C 参数语义、多 PDK 泛化；
- 按内部工具定位（不做商业产品），**2–4 周可到"能给别人用的 v0.9"**（在上述 P0/P1 完成后）。

**不建议**：从零做 GUI 或复刻 SPT 的全部功能（引脚重连、版图）；那是产品级投入，且偏离"尺寸迁移"这个我们真正的差异点。

## 五、路线图（建议）

1. **Phase 1（3–5 天）**：P0 —— 原理图导出闭环、噪声列刷新、R/C 映射；CLI 雏形（`amigrate table/solve/map/verify`）。
2. **Phase 2（1–2 周）**：P1 —— 引脚检查、完整统计蒙卡、CMRR/offset/PSRR、project.toml + 一键复现 + 报告模板。
3. **Phase 3**：用**乘法器**做第二个电路验证复用成本；再决定是否投 GUI/多 PDK 推广。

## 六、风险

| 风险 | 影响 | 对策 |
|---|---|---|
| PDK NDA | 工具不能带 PDK 分发 | 只发代码 + 适配 TOML；PDK 由用户本地挂载 |
| Virtuoso 环境依赖 | 原理图分支不可移植 | 网表分支保底，原理图分支可选 |
| 器件映射靠人工确认 | 换 PDK 成本高 | device-map.toml + 校验脚本 + 失败即报错 |
| 维护成本 | 脚本散落 | CLI 收口 + 单测 + runs 证据规范 |
## 2026-11-26 完成情况（补记）

- 原理图→网表导出：已打通（`skill/export_netlist.il`），与手写 v2 网表 diff 一致（11 器件/端口/连接/尺寸）。
- 噪声列：已用 Spectre noise 实测拟合刷新（`tools/add_noise.py`，`noise_src=sim_fit`）。
- R/C 映射：查明源图用 analogLib 理想 R/C（仿真不需映射）；版图级目标已调研（`rhrpo`: segW/segL/rsh；`mim2_tm`: w/l/c）。
- CLI：`tools/amigrate.py` + `amigrate.toml`；报告：`tools/gen_report.py` → `docs/reports/verification-2026-11-26.md`。
- 交接文档：`docs/交接文档-2026-11-26.md`。
- 仍待：CMRR/offset/PSRR 角集、完整统计蒙卡（tox/β）、第二个电路（乘法器）、GUI。
