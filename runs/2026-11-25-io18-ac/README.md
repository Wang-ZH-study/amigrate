# OPA_D 1.8V（n33/p33）AC 开环增益验证（2026-11-25）

## 方法

- 拓扑取自上游 AC 网表 `upstream_net.scs`（OPA_D_AC，subckt OPA_D + 补偿 Rz/Cc/Rb）。
- 测试台：VDD=1.8V，VCM=0.9V，VINP 叠加 AC=1V；OUT 与 VINM 之间接 **1GH 电感**（DC 闭环定工作点、AC 开路），VINM 再经 **1kΩ 到 VCM**（AC 对地）；`|OUT|` 即开环增益。
- 源/目标各一份网表：源用上游 180nm 尺寸，目标用我们 13mmrf n33/p33 解出的尺寸（`src_net.scs` / `tgt_net.scs`，由 `tools/make_io18_testbench.py` 生成）。

> 踩坑记录：VINM 隔离电阻最初用 1GΩ，与 1GH 电感在低频分压，反馈没真正断开，测出来只有 16dB（假象）。改成 1kΩ 后正常。

## 结果（Spectre .ac，1Hz–100MHz，dec=10）

| 设计 | DC 增益 | UGF | 相位裕度 |
|---|---|---|---|
| 源（smic18ee，上游尺寸） | **76.68 dB** | 29.2 MHz | 51.3° |
| 目标（13mmrf n33/p33，我们的尺寸） | **61.78 dB** | 15.5 MHz | 75.4° |

**目标比源低 14.9 dB，UGF 低一半**——与单管 self_gain 预测一致（n33 本征增益 123.2→56.3，差 2.2×≈6.8dB，两级相乘 ≈13.6dB）。

## 结论

1. 测试台可信：源设计测出 76.68 dB，与上游设计目标（76–78 dB）吻合，说明方法正确；
2. **增益确实不如预期**：61.78 dB，缺口约 15 dB——不是脚本误差，是 n33 在 1.8V 下本征增益不足的物理结果；
3. 相位裕度 75.4° 很好；UGF 15.5 MHz 偏低（源 29.2MHz），说明当前尺寸偏保守/偏慢；
4. 下一步（08）：对 M3/M4/M6 加大 L（0.5→1.0/1.5µm）提高 ro，重解尺寸并重跑本测试台，目标把增益补到 ≥70 dB 并复核 UGF/PM。

## 复现

```bash
python tools/make_io18_testbench.py
# scp src_net.scs tgt_net.scs run_ac.sh 到 VM /tmp，bash /tmp/run_ac.sh
python tools/parse_ac_gain.py runs/2026-11-25-io18-ac/src.ac runs/2026-11-25-io18-ac/tgt.ac
```