# 13mmrf 档位/CDF 查询 + 07B SKILL 试点（2026-11-25）

## 查询结论（cdf_probe.log）

- 13mmrf 库 `smic13mmrf_1233`（216 cells）已挂在 `~/cds.lib`。
- MOS：`n12/p12`（1.2V core）、`n33/p33`（3.3V IO），另有 `*_mis_ckt`、`*_ckt_rf` 变体。
- 电容：`mim1 / mim15 / mim2_tm / mim3`。
- **13mmrf MOS 的 CDF 参数是 `w、l、m、fingers、mismod`——指数用 `fingers`，没有 `nf`。**
- 18ee：`n18e2r/p18e2r`、`rhrpo`（参数是 `r/segW/segL/rsh` 一类）、`mime2r`（`w/l/c`）。
- 源库：`weekfour_last`（/home/IC/weekfour_last）；源 PDK 库 `smic18ee`。

## 试点结果（pilot.log）

- 建库 `port_pilot` + 建 cell `pilot_mos` + 放源实例 `smic18ee/n18e2r`：✅
- 跨 PDK 换器件：**✅ `changed=t`，M1 master 变为 `smic13mmrf_1233/n12`**。
- selftest 尺寸写入（apply_sizes）：❌ VM 的 SKILL 读 CSV 失败（`lineread` 返回 token 而非整行；`readLine` 未定义；`gets` 调用后进程 panic）。
- 换器件过程有 32 条 `PasCdfGetDpt` 噪声（pcell 默认值读取），非致命。
- 未连线，schCheck 报 D/G/S/B floating（预期）。

## 结论

"表 → SKILL 换器件"这一段**方法上已验证可行**；卡点是 SKILL 的文件 I/O 兼容性，不是流程问题。

## 下一步

1. 硬编码尺寸验证 `dbSet w/l/fingers` + CDF 回调；
2. CSV 改为 Python 生成 SKILL alist（`load` 直接执行），绕过 SKILL 文件 I/O；
3. 带连线的测试原理图 → 导网表 → `.op`；
4. 通过后接 8 管全量与 07A 对照。

## 文件

- `cdf_probe.log`：cell/CDF 清单（本目录，未入库）
- `pilot.log`：试点过程（本目录，未入库）
- 模板：`skill/conv.config`、`skill/apply_sizes.il`、`skill/pilot_run.il`、`skill/cdf_probe.il`
- 进度页：`docs/progress-07b.html`
## 硬编码尺寸实验（2026-11-25 18:25，pilot2–pilot4）

- 建 pcell 实例并 dbSet w/l：**无效**。写 "2e-6"/"2u" 后 dbGet 与重开仍是 w="280n" l="130n"。
- w/simW/fingers 也写不进；dbReplaceProp 参数顺序不对（报 invalid propType）。
- inst~>master~>isParamCell = **nil**，view="symbol" → 
12 的 symbol **不是 pcell**；simW=iPar("fw")，w/l 是 CDF 计算参数。
- **判断**：不是 CSV 读取问题，也不是 SKILL 语法问题，而是 **PDK 实例类型 / 参数写入 API** 问题。
- **下一步**：只读打开上游 weekfour_last/OPA_D，打印实例的 master view 与属性名/值，照抄上游的存法。

## 真实副本试点（2026-11-25 19:40，pilot5/6）——写入机制已打通

- 复制 weekfour_last/OPA_D 到 port_pilot/OPA_D（16 实例），上游实例存法：w="9.27u" l="500n" fingers="2" m="1" fw="4.635u"（w=总宽，fw=w/fingers）。
- bConvertComponentParams + n/p 映射配置：**8/8 MOS 换成 13mmrf**（M1→p12、M3→n12），converted instances=8。
- **写尺寸结论**：dbSet 静默失败；dbReplaceProp inst "w" 'string "9u" 成功——M1 写 w="9u" l="500n" fingers="2"，**重开验证仍是 9u/500n/2**。
- 因此 dbSet（非 API 问题）是一路卡点；pply_sizes.il 已改用 dbReplaceProp + %gu 单位串。
- 剩余：批量写 8 管 → 导网表 → .op。
