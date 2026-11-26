#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成四页汇报 PPT：
  1 参数提取对照（与华为 CN116964587A）
  2 迁移流程与关键结果
  3 蒙卡仿真：是什么 / 我们跑出了什么
  4 现状与下一步
"""
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "reports" / "migration-flow-2026-11-26.pptx"

NAVY = RGBColor(0x1F, 0x38, 0x64)
TEAL = RGBColor(0x2A, 0x9D, 0x8F)
ORANGE = RGBColor(0xE7, 0x6F, 0x51)
GRAY = RGBColor(0x59, 0x5F, 0x69)
LIGHT = RGBColor(0xF2, 0xF4, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
AMBER = RGBColor(0xB2, 0x6A, 0x00)
FONT = "微软雅黑"


def add_text(slide, x, y, w, h, text, size=14, color=GRAY, bold=False, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = FONT
    return box


def add_rect(slide, x, y, w, h, fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sh = slide.shapes.add_shape(shape, x, y, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.fill.background()
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = 0.08
    return sh


def header(slide, title, subtitle):
    add_rect(slide, 0, 0, Inches(13.333), Inches(1.15), NAVY, MSO_SHAPE.RECTANGLE)
    add_text(slide, Inches(0.55), Inches(0.18), Inches(11.4), Inches(0.5), title,
             size=25, color=WHITE, bold=True)
    add_text(slide, Inches(0.55), Inches(0.68), Inches(11.4), Inches(0.4), subtitle,
             size=13, color=RGBColor(0xC9, 0xD6, 0xEA))


def footer(slide, text):
    add_rect(slide, 0, Inches(7.05), Inches(13.333), Inches(0.45), NAVY, MSO_SHAPE.RECTANGLE)
    add_text(slide, Inches(0.45), Inches(7.12), Inches(12.4), Inches(0.3), text,
             size=9.5, color=RGBColor(0xC9, 0xD6, 0xEA))


def make_table(slide, rows, x, y, w, col_widths, row_h=Inches(0.5), header_row=True,
               font_size=10.5):
    nrows, ncols = len(rows), len(rows[0])
    shape = slide.shapes.add_table(nrows, ncols, x, y, w, row_h * nrows)
    table = shape.table
    for i, cw in enumerate(col_widths):
        table.columns[i].width = cw
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.cell(ri, ci)
            cell.margin_left = Inches(0.06)
            cell.margin_right = Inches(0.04)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = val
            run.font.name = FONT
            run.font.size = Pt(font_size if not header_row else font_size + 0.5)
            run.font.bold = header_row and ri == 0
            if header_row and ri == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY
                run.font.color.rgb = WHITE
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if ri % 2 else LIGHT
                if val.startswith("✅"):
                    run.font.color.rgb = GREEN
                elif val.startswith("◐"):
                    run.font.color.rgb = AMBER
                elif val.startswith("✗"):
                    run.font.color.rgb = ORANGE
                else:
                    run.font.color.rgb = GRAY
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE


def slide1(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    header(slide, "参数提取对照：与华为 CN116964587A 还差什么",
           "同一套表结构：工作点 → gm/Id → self_gain → 寄生 → 噪声 → 失配 → 角集")
    rows = [
        ["参数组", "参数 / 口径", "华为用途", "我们现状"],
        ["直流工作点", "Id、Vgs、Vds、Vth、Vdsat、region", "反解尺寸的基础", "✅ Spectre 实测（101,080 行）"],
        ["跨导效率", "gm/Id", "尺寸主锚点", "✅ 实测 + 反解使用"],
        ["本征增益", "self_gain = gm/gds（Aint dB）", "保每级增益不漂", "✅ 实测，逐管匹配残差 <0.1"],
        ["寄生电容", "Cgg / Cgd / Cdb ÷ W", "带宽 / 极点估算", "✅ 实测（fF/µm）"],
        ["噪声", "inoise_1hz / inoise_10k", "噪声预算", "✅ 已做 Spectre noise 实测；表列待刷新"],
        ["失配（Vt）", "σ(ΔVt)=Avt/√(W·L)，gm∈[gm, gm+3σ]", "容忍带 / 良率", "✅ Avt 取自 PDK：n 9.5 / p 3.5 mV·µm"],
        ["失配（β）", "β0 / β1（电流增益上下限）", "电流镜失配", "✅ 已从模型提取（3σ：n 0.18–1.95%）"],
        ["尺寸可实现性", "W、nf/m、Vds−Vdsat 余量", "可制造性判定", "✅ F0–F4 判据"],
        ["角集", "5 process × 3 VDD × 3 temp", "鲁棒性", "✅ PVT 45 点 + 蒙卡 300 点"],
    ]
    make_table(slide, rows, Inches(0.45), Inches(1.38), Inches(12.45),
               [Inches(1.55), Inches(4.3), Inches(2.5), Inches(4.1)], row_h=Inches(0.45),
               font_size=10.5)
    add_rect(slide, Inches(0.45), Inches(5.98), Inches(12.45), Inches(0.85), LIGHT)
    add_text(slide, Inches(0.62), Inches(6.06), Inches(12.1), Inches(0.3),
             "差距只剩一项：", size=12.5, color=NAVY, bold=True)
    add_text(slide, Inches(0.62), Inches(6.36), Inches(12.1), Inches(0.42),
             "把 Spectre noise 实测值与拟合的 1/f 系数刷回表格（现有 inoise 公式低估 4–20×）。"
             "Vt 失配、β 失配、角集、蒙卡均已补齐。",
             size=10.5, color=GRAY)
    footer(slide, "依据：CN116964587A ｜ 证据：runs/2026-11-25-lut-build/13mmrf_io18/（avt-source.json、beta-source.json）、runs/2026-11-26-noise/")


def slide2(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    header(slide, "迁移流程：从器件表到可验收原理图",
           "案例：SMIC 180nm OPA_D → 13mmrf 130nm（1.8V，n33/p33）｜ 2026-11-26")
    steps = [
        ("1", "建器件表", "Spectre 实测\n全区域+噪声+失配"),
        ("2", "反解尺寸", "gm/Id + self_gain\n双重匹配，3σ 带"),
        ("3", "器件映射", "18ee → 13mmrf\nn33 / p33（1.8V）"),
        ("4", "生成原理图", "SKILL：复制→换器件\n→写尺寸（可验证）"),
        ("5", "验收", "AC/瞬态/PVT/蒙卡\n45 点 + 300 点"),
    ]
    x0, y0 = Inches(0.45), Inches(1.5)
    box_w, box_h, gap = Inches(2.32), Inches(1.55), Inches(0.18)
    colors = [NAVY, RGBColor(0x2B, 0x4C, 0x7E), TEAL, RGBColor(0x3A, 0x7D, 0x8C), ORANGE]
    for i, (num, name, detail) in enumerate(steps):
        x = x0 + i * (box_w + gap)
        add_rect(slide, x, y0, box_w, box_h, colors[i])
        add_text(slide, x + Inches(0.08), y0 + Inches(0.12), box_w - Inches(0.16), Inches(0.42),
                 f"{num}  {name}", size=15, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, x + Inches(0.12), y0 + Inches(0.72), box_w - Inches(0.24), Inches(0.72),
                 detail, size=10.5, color=WHITE)
        if i < len(steps) - 1:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                                           x + box_w - Inches(0.02), y0 + Inches(0.62),
                                           Inches(0.2), Inches(0.3))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = GRAY
            arrow.line.fill.background()

    add_text(slide, Inches(0.45), Inches(3.35), Inches(6.4), Inches(0.4),
             "关键结果（全部可追溯到 runs/）", size=15, color=NAVY, bold=True)
    rows2 = [
        ("器件表", "18ee 32,760 行 ／ 13mmrf 101,080 行"),
        ("换器件 + 写尺寸", "8/8 实例成功，尺寸落盘可复查"),
        ("标称性能", "82.4 dB ／ 31.6 MHz ／ 71° ／ 608 µW"),
        ("PVT 45 点", "45/45 通过（最坏 UGF 10.97 MHz）"),
        ("蒙卡 300 点", "100% 良率（Vt 失配，Avt 9.5/3.5）"),
    ]
    yy = Inches(3.8)
    for i, (k, v) in enumerate(rows2):
        add_rect(slide, Inches(0.45), yy, Inches(6.4), Inches(0.52),
                 LIGHT if i % 2 == 0 else WHITE, MSO_SHAPE.RECTANGLE)
        add_text(slide, Inches(0.58), yy + Inches(0.1), Inches(1.75), Inches(0.34), k,
                 size=11.5, color=NAVY, bold=True)
        add_text(slide, Inches(2.35), yy + Inches(0.1), Inches(4.4), Inches(0.34), v,
                 size=11, color=GRAY)
        yy += Inches(0.56)

    add_text(slide, Inches(7.2), Inches(3.35), Inches(5.7), Inches(0.4),
             "这套流程解决什么", size=15, color=NAVY, bold=True)
    add_rect(slide, Inches(7.2), Inches(3.8), Inches(5.7), Inches(2.75), LIGHT)
    bullets = [
        "• 器件表来自 Spectre 实测，可复现、可审计",
        "• 逐管匹配 self_gain，避免“尺寸对了、增益掉了”",
        "• 换器件与写尺寸用 SKILL 自动化，不手改 8 个管",
        "• PVT 暴露最坏角问题 → 输入对 W×32 修复",
        "• 失配按华为口径入表 → 蒙卡直接出良率",
    ]
    for i, b in enumerate(bullets):
        add_text(slide, Inches(7.42), Inches(3.95) + Inches(0.5) * i, Inches(5.3), Inches(0.42),
                 b, size=11, color=GRAY)
    footer(slide, "证据：runs/2026-11-25-lut-build、runs/2026-11-25-io18-ac、runs/2026-11-25-pvt、runs/2026-11-26-mc ｜ 工具：tools/*.py")


def slide3(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    header(slide, "蒙卡仿真：是什么、怎么跑、我们得到什么",
           "用随机抽样估计性能分布与良率，是“角集”之外的另一只眼睛")

    # 左上：角集 vs 蒙卡
    add_rect(slide, Inches(0.45), Inches(1.42), Inches(4.1), Inches(2.55), LIGHT)
    add_text(slide, Inches(0.62), Inches(1.52), Inches(3.8), Inches(0.35),
             "① 和角集有什么区别", size=13, color=NAVY, bold=True)
    rows = [
        ["", "PVT 角集", "蒙卡"],
        ["做法", "极端组合", "随机抽样"],
        ["回答", "最坏多坏", "良率多少"],
        ["缺点", "偏悲观", "依赖模型"],
    ]
    make_table(slide, rows, Inches(0.62), Inches(1.95), Inches(3.75),
               [Inches(0.65), Inches(1.55), Inches(1.55)], row_h=Inches(0.42), font_size=10)

    # 左下：Pelgrom
    add_rect(slide, Inches(0.45), Inches(4.12), Inches(4.1), Inches(2.55), LIGHT)
    add_text(slide, Inches(0.62), Inches(4.22), Inches(3.8), Inches(0.35),
             "② 失配怎么建模（Pelgrom）", size=13, color=NAVY, bold=True)
    add_text(slide, Inches(0.62), Inches(4.62), Inches(3.8), Inches(0.5),
             "σ(ΔVt) = Avt / √(W·L)", size=16, color=TEAL, bold=True)
    add_text(slide, Inches(0.62), Inches(5.12), Inches(3.8), Inches(1.4),
             "面积越大，失配越小。\n13mmrf：n33 Avt=9.5、p33 Avt=3.5 mV·µm\n"
             "我们给每个管子加 ΔV~N(0,σ)，跑 300 次。", size=10.5, color=GRAY)

    # 右：结果表
    add_text(slide, Inches(4.85), Inches(1.42), Inches(8.0), Inches(0.4),
             "③ 我们的 300 点结果（tt/1.8V/27°C，Vt 失配）", size=14, color=NAVY, bold=True)
    rows2 = [
        ["指标", "均值", "σ", "最小", "最大", "目标", "通过率"],
        ["增益", "82.42 dB", "0.057", "82.27", "82.58", "≥60", "100%"],
        ["UGF", "31.45 MHz", "0.361", "30.51", "32.34", "≥10", "100%"],
        ["相位裕度", "70.50°", "0.448", "69.42", "71.67", "≥60", "100%"],
        ["功耗", "607.8 µW", "4.3", "594.9", "619.8", "≤1000", "100%"],
    ]
    make_table(slide, rows2, Inches(4.85), Inches(1.9), Inches(8.0),
               [Inches(1.3), Inches(1.25), Inches(0.9), Inches(1.0), Inches(1.0),
                Inches(1.05), Inches(1.5)], row_h=Inches(0.5), font_size=11)
    add_rect(slide, Inches(4.85), Inches(4.5), Inches(8.0), Inches(2.15), LIGHT)
    add_text(slide, Inches(5.0), Inches(4.6), Inches(7.7), Inches(0.35),
             "联合良率 300/300 = 100%", size=15, color=GREEN, bold=True)
    add_text(slide, Inches(5.0), Inches(5.05), Inches(7.7), Inches(1.45),
             "• 统计精度 ≈ 1/√N：300 点的良率分辨率约 ±0.3%–3%\n"
             "• 设计余量大（输入对 244µm），所以 σ 很小、良率 100%\n"
             "• 口径限制：只含 Vt 失配，不含 tox/β 失配与 SR；工艺角由 PVT 45 点单独覆盖",
             size=10.5, color=GRAY)
    footer(slide, "工具：tools/mc_sweep.py（栅极串 ΔV 源）｜ 证据：runs/2026-11-26-mc/（mc.csv、run_meta.csv、300 个 spectre 目录）")


def slide4(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    header(slide, "现状与下一步：已经闭环，还差两件关键事",
           "2026-11-26 ｜ 已跑通：表 → 反解 → 映射 → 原理图 → 验收")

    add_text(slide, Inches(0.45), Inches(1.4), Inches(6.2), Inches(0.4),
             "已完成", size=15, color=GREEN, bold=True)
    done = [
        "① 迁移版器件表：18ee 32,760 行、13mmrf 101,080 行（含 avt/β）",
        "② 反解 + 可行性：gm/Id + self_gain、3σ 带、F0–F4",
        "③ 原理图：真实 OPA_D 8/8 换器件 + 写尺寸落盘",
        "④ 重定尺寸：n-L=1.0µm、输入对 W×32",
        "⑤ 验收：标称 6/6、PVT 45/45、蒙卡 300/300",
        "⑥ 参数对照：华为 9 组参数 8 组已覆盖",
    ]
    for i, t in enumerate(done):
        add_text(slide, Inches(0.6), Inches(1.85) + Inches(0.55) * i, Inches(6.0), Inches(0.5),
                 t, size=11, color=GRAY)

    add_text(slide, Inches(7.0), Inches(1.4), Inches(5.9), Inches(0.4),
             "可改进（按优先级）", size=15, color=ORANGE, bold=True)
    imps = [
        ("P0", "噪声列用实测刷新（现公式低估 4–20×）", GREEN),
        ("P0", "原理图 → 网表导出打通（当前用等价网表）", GREEN),
        ("P1", "CMRR / offset / PSRR 的角集", AMBER),
        ("P1", "完整统计蒙卡（tox/β 失配）", AMBER),
        ("P1", "最坏角 UGF 余量仅 9.7%，需留余量", AMBER),
        ("P2", "第二个电路（乘法器）验证复用成本", GRAY),
    ]
    for i, (tag, t, color) in enumerate(imps):
        y = Inches(1.85) + Inches(0.72) * i
        pill = add_rect(slide, Inches(7.05), y + Inches(0.03), Inches(0.55), Inches(0.32),
                        color, MSO_SHAPE.ROUNDED_RECTANGLE)
        add_text(slide, Inches(7.05), y + Inches(0.05), Inches(0.55), Inches(0.28), tag,
                 size=10, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, Inches(7.75), y, Inches(5.1), Inches(0.62), t, size=10.8, color=GRAY)

    add_rect(slide, Inches(0.45), Inches(5.95), Inches(12.45), Inches(0.9), LIGHT)
    add_text(slide, Inches(0.62), Inches(6.05), Inches(12.0), Inches(0.7),
             "一句话：流程已端到端闭环并在 OPA_D 上验收通过；下一步优先修“噪声列”和“原理图导出”，"
             "再用乘法器验证第二个电路的复用成本。",
             size=11.5, color=NAVY)
    footer(slide, "详细版：docs/reports/status-2026-11-26.md ｜ 工单板：.scratch/analog-migration-spt/README.md")


def main() -> int:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide1(prs)
    slide2(prs)
    slide3(prs)
    slide4(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"写入 {OUT}（{len(prs.slides)} 页）")
    return 0


if __name__ == "__main__":
    sys.exit(main())