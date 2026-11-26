# SKILL 脚本：什么时候用、怎么用（一页记录）

> 2026-11-25 决策：**本轮砍掉 SKILL 主线**，07 号工单改走网表映射器。
> 本文只留一页"将来什么时候该把它拿回来、拿回来怎么做"。技术细节在 [lut-and-solver.md](lut-and-solver.md) B 节。

## 一句话

SKILL 脚本是 **Virtuoso 里的"结构搬运自动化"**：换器件 master、改参数名与单位、重算 CDF、按层次批量，输出目标库的 **schematic**（不是网表）。
它**不定尺寸、不保证性能、不重连引脚**，所以迁移的数值与验收仍要自己做。

## 什么时候重新启用

| 场景 | 是否用 SKILL |
|---|---|
| **交付物必须是 PDK_13mmrf 原理图**（后续 LVS/版图/评审要读图） | ✅ 用，否则只能重画 |
| **同节点迁移**（180→180 换厂/换变体，尺寸≈1:1） | ✅ 主力，几乎就是全部工作 |
| **规模化**：整库/多个设计反复迁移，配置可复用 | ✅ 划算 |
| 只要网表 + PVT 结果（本轮形态） | ❌ 不用，Python 网表映射器更直接 |

## 怎么做（四步）

1. **复制库**：先把源库 `dbCopyCellView` 复制成目标库（脚本原地改，不复制会改坏源库）。
2. **挂两套 PDK**：同一个 Virtuoso session 里 `smic18ee` 与 `smic13mmrf` 都在 Library Manager 里。
3. **写 `conv.config`**（S 表达式，可进 git；OPA_D 约 12–15 条）：

```skill
(
  (nil fromLib "smic18ee" fromCell "n18e2r" toLib "smic13mmrf" toCell "n12"
   runCallbacks t
   params (("w" "w") ("l" "l") ("nf" "nf")))
  (nil fromLib "smic18ee" fromCell "p18e2r" toLib "smic13mmrf" toCell "p12"
   runCallbacks t
   params (("w" "w") ("l" "l") ("nf" "nf")))
  (nil fromLib "smic18ee" fromCell "rhrpo" toLib "smic13mmrf" toCell "primRes2"
   params (("w" "w") ("l" "l" fixResLength))   ; 方块电阻变了，长度要按 rsh 换算
   )
)
```

4. **跑并核对**：`abConvertComponentParamsHier("conv.config")` → `schCheck` → 导出网表 → 与源网表 diff → 手核 2 个器件的 W/L/nf/单位。

## 三条硬边界

- **不重连引脚**：引脚名/数量一变就断，必须网表 diff 逐条核（3 端 vs 4 端是最大风险）。
- **不定尺寸**：搬过去的 W/L 是源值，性能不保证（"能仿，数先别信"）。
- **不清旧属性**：旧 PDK 私有 CDF 属性会残留成 user property；派生参数可能"显示对、网表旧值"。

## 参考

- 脚本原件（不入库）：`research/attachments/abConvertComponentParams.il`、`abInvokeCdfCallbacks.il`
- 出处：Designer's Guide Community，Andrew Beckett（Cadence），2009 年公开附件
- 机制拆解（源码级）：[lut-and-solver.md](lut-and-solver.md) §B
- 收益账本与决策规则：git 历史（commit `ec967d6` 之前的 `skill-to-13mmrf.md` 全文）