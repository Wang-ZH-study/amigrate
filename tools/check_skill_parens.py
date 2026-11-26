#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查 SKILL (.il) 文件的括号平衡（跳过字符串与 ; 注释），打印失衡位置。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def strip_line(line: str) -> str:
    out = []
    in_str = False
    esc = False
    for ch in line:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            out.append(" ")
            continue
        if ch == '"':
            in_str = True
            out.append(" ")
            continue
        if ch == ";":
            break
        out.append(ch)
    return "".join(out)


def check(path: Path) -> int:
    depth = 0
    bad = []
    in_block = False
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line
        if in_block:
            end = s.find("*/")
            if end < 0:
                continue
            s = s[end + 2:]
            in_block = False
        start = s.find("/*")
        while start >= 0:
            end = s.find("*/", start + 2)
            if end < 0:
                s = s[:start]
                in_block = True
                break
            s = s[:start] + " " + s[end + 2:]
            start = s.find("/*")
        s = strip_line(s)
        d = s.count("(") - s.count(")")
        depth += d
        if depth < 0:
            bad.append((i, depth, line.strip()))
            break
    print(f"{path}: 最终深度 {depth}" + ("" if depth == 0 else "  <-- 不平衡"))
    for b in bad:
        print(f"  第 {b[0]} 行深度变负：{b[2]}")
    return 0 if depth == 0 and not bad else 1


if __name__ == "__main__":
    rc = 0
    for arg in sys.argv[1:]:
        rc |= check(Path(arg))
    sys.exit(rc)