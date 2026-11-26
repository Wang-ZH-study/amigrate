# auto-IC-move — 模拟电路迁移工作区

本工作区只做两件事：

1. **把模拟电路迁移的公开文献盘清楚**——路线、判据、已证明做不了的地方。
2. **把 WiCkeD SPT（Schematic Porting Tool）摸清并尝试应用到真实设计上**——它现在是什么状态、能不能拿到、拿不到时用什么等价办法。

## 当前状态

- **工单 01 已完成**：仓库骨架、`AGENTS.md` 约定、目录结构、首次提交 `7821e5d`。
- **工单 02 已完成**：证据速览 [docs/research/README.md](docs/research/README.md) + 路线 ADR [docs/decisions/0001-migration-route.md](docs/decisions/0001-migration-route.md)。
- **工单 03 已完成**：验收规格 [specs/migration-spec.toml](specs/migration-spec.toml) + 验收清单 [docs/acceptance-checklist.md](docs/acceptance-checklist.md) + 判卷脚本 [tools/check_spec.py](tools/check_spec.py)（`--selftest` 5/5 通过，空证据退出码 1）。
- 两份调研已落库（`research/`）：
  - [模拟电路迁移文献综述](research/analog-migration-literature.md)：40 条题录 + 四条技术路线 + 五层验收口径 + 五个 gap。
  - [WiCkeD SPT 现状](research/wicked-spt-state.md)：2011 年发布、2024 年被 Cadence 收购、只搬原理图不保证性能、无开源等价物。
  - [SPT 还能不能拿到、要装什么](research/spt-obtainability.md)：无合法公开下载/试用；RHEL 6/7/8 + Virtuoso + 两套 PDK + license；本周零成本路径是 IC618 里跑 Cadence 公开 SKILL 脚本。
- 工作计划已拆成工单：[工单索引](.scratch/analog-migration-spt/README.md)。
- **2026-11-25 决策：砍掉 SKILL 原理图迁移主线**，07 改为 Python 网表映射器。理由：本轮交付物是 13mmrf 网表 + PVT 结论，不需要 Virtuoso 原理图；单个跨节点小电路上 SKILL 时间收益≈0。SKILL 做法压缩成一页记录：[docs/porting/skill-to-13mmrf.md](docs/porting/skill-to-13mmrf.md)。
- 下一张可开工：**04 源端基线包**；**05** 已完成 05.1/05.5/05.6（LUT 表结构 [specs/device-lut-schema.toml](specs/device-lut-schema.toml)、反解器 `tools/solve_lw.py`、自洽回归 8/8 见 [runs/2026-11-25-lut-selfcheck](runs/2026-11-25-lut-selfcheck/README.md)），05.2 需要 VM。

## 已确认的两个项目边界（2026-11-25）

| 项 | 决定 | 理由 |
|---|---|---|
| 迁移配对 | **同厂跨节点**：smic18ee（180nm）上的 OPA_D → `PDK_13mmrf_1P6M_30k`（130nm）；暂时不碰 X-FAB XT018 | 跨 foundry 差异太大；13mmrf 在 VM 内齐全（216 OA cell + Calibre DRC/LVS/xRC），能一次跑通全流程。代价：跨节点、头寸要重排（2026-11-25 修订，原定 smic18mmrf） |
| WiCkeD SPT | **没有许可，从零引入**；工单同时准备"买/试用"和"自建等价流程"两条路 | SPT 已并入 Cadence，报价与可得性需实际问；不能被工具卡死 |

## 目录约定

```
research/                      调研笔记（已完成）
.scratch/analog-migration-spt/ 工单（一批一文件，按依赖编号）
docs/                          决策记录、验收清单（工单 01/03 建）
specs/                         机器可读的迁移规格（工单 03 建）
netlists/                      源/目标网表（工单 04/07 建）
tools/                         映射器、仿真驱动、报告生成（工单 07/08 建）
runs/                          每次实验的产物（不入库大文件）
```

## 阅读顺序

先读 [工单索引](.scratch/analog-migration-spt/README.md) 看依赖图，再从没有前置的 01、02 开始。
## 快速入口（2026-11-26）
- 交接文档：docs/交接文档-2026-11-26.md
- CLI：python tools/amigrate.py status
- 验证报告：docs/reports/verification-2026-11-26.md
- 系统设计：docs/porting/migration-system-design.md

