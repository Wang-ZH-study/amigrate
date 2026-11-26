#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""amigrate 桌面版（tkinter，零第三方依赖）。

用法：双击 `启动迁移工具.bat`，或：
    pythonw tools\\amigrate_app.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import webui as core  # noqa: E402  （复用 ssh/环境/任务后端）

PDKS = [
    ("SMIC18（smic18ee）", "smic18ee_2P6M_20100810"),
    ("SMIC13（13mmrf）", "PDK_13mmrf_1P6M_30k"),
]


def set_job(kind: str) -> None:
    core.STATE["job"] = {"id": str(int(time.time())), "kind": kind, "status": "running",
                         "log": [], "result": {}, "pct": 0, "stage": "启动", "stages": []}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("amigrate · 模拟电路迁移工具 v1.0")
        self.geometry("980x720")
        self.configure(bg="#f6f8fb")
        try:
            self.iconbitmap(str(ROOT / "assets" / "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        self._build()
        self.after(300, self.refresh_env)

    # ---------------- UI
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        top = tk.Frame(self, bg="#1f3864")
        top.pack(fill="x")
        tk.Label(top, text="amigrate · 模拟电路迁移工具", bg="#1f3864", fg="white",
                 font=("Microsoft YaHei", 16, "bold")).pack(side="left", padx=14, pady=10)
        tk.Label(top, text="SMIC18 ↔ SMIC13", bg="#1f3864", fg="#c9d6ea",
                 font=("Microsoft YaHei", 10)).pack(side="left", padx=6)

        # 环境
        env = tk.LabelFrame(self, text="0. 环境检测", bg="#f6f8fb", font=("Microsoft YaHei", 10, "bold"))
        env.pack(fill="x", **pad)
        self.env_label = tk.Label(env, text="检测中…", bg="#f6f8fb", anchor="w",
                                  font=("Microsoft YaHei", 10))
        self.env_label.pack(side="left", padx=8)
        tk.Button(env, text="重新检测", command=self.refresh_env).pack(side="right", padx=8, pady=4)

        # 源设计
        src = tk.LabelFrame(self, text="1. 源设计", bg="#f6f8fb", font=("Microsoft YaHei", 10, "bold"))
        src.pack(fill="x", **pad)
        self.src_lib = self._field(src, "源库", "weekfour_last", 0, 0)
        self.src_cell = self._field(src, "原理图名（cell）", "OPA_D", 0, 2)
        tk.Label(src, text="源 PDK", bg="#f6f8fb").grid(row=1, column=0, sticky="w", padx=6)
        self.src_pdk = ttk.Combobox(src, values=[p[0] for p in PDKS], state="readonly", width=26)
        self.src_pdk.current(0)
        self.src_pdk.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        # 目标设计
        tgt = tk.LabelFrame(self, text="2. 目标设计", bg="#f6f8fb", font=("Microsoft YaHei", 10, "bold"))
        tgt.pack(fill="x", **pad)
        self.out_lib = self._field(tgt, "输出库", "port_pilot", 0, 0)
        self.out_cell = self._field(tgt, "输出原理图名", "OPA_D_13mmrf", 0, 2)
        tk.Label(tgt, text="目标 PDK", bg="#f6f8fb").grid(row=1, column=0, sticky="w", padx=6)
        self.tgt_pdk = ttk.Combobox(tgt, values=[p[0] for p in PDKS], state="readonly", width=26)
        self.tgt_pdk.current(1)
        self.tgt_pdk.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        # 操作
        ops = tk.Frame(self, bg="#f6f8fb")
        ops.pack(fill="x", **pad)
        tk.Button(ops, text="查找原理图", command=self.do_lookup).pack(side="left", padx=4)
        tk.Button(ops, text="开始迁移（结构）", command=self.do_convert).pack(side="left", padx=4)
        tk.Button(ops, text="PVT 仿真 45 点", command=self.do_pvt).pack(side="left", padx=4)
        tk.Button(ops, text="打开输出目录", command=self.open_out).pack(side="left", padx=4)

        # 进度
        prog = tk.LabelFrame(self, text="进度", bg="#f6f8fb", font=("Microsoft YaHei", 10, "bold"))
        prog.pack(fill="both", expand=True, **pad)
        self.bar = ttk.Progressbar(prog, maximum=100)
        self.bar.pack(fill="x", padx=8, pady=6)
        self.stage = tk.Label(prog, text="准备中…", bg="#f6f8fb", anchor="w",
                              font=("Microsoft YaHei", 9))
        self.stage.pack(fill="x", padx=8)
        self.log = tk.Text(prog, height=18, bg="#0f172a", fg="#d7e2f1", insertbackground="#fff",
                           font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=6)
        self.result = tk.Label(prog, text="", bg="#f6f8fb", anchor="w", fg="#178a4c",
                               font=("Microsoft YaHei", 9), justify="left")
        self.result.pack(fill="x", padx=8, pady=4)
        self.out_dir = None

    def _field(self, parent, label, default, row, col):
        tk.Label(parent, text=label, bg="#f6f8fb").grid(row=row, column=col, sticky="w", padx=6)
        ent = tk.Entry(parent, width=28)
        ent.insert(0, default)
        ent.grid(row=row, column=col + 1, sticky="w", padx=6, pady=4)
        return ent

    # ---------------- 环境
    def refresh_env(self) -> None:
        self.env_label.config(text="检测中…")

        def work():
            env = core.env_info()
            txt = ("VM 在线" if env["vm"] else "VM 不可达") + " ｜ " + \
                  ("Virtuoso 运行中" if env["virtuoso"] else "Virtuoso 未运行") + \
                  " ｜ PDK：" + " / ".join(env["pdks"])
            self.env_label.config(text=txt, fg="#178a4c" if env["vm"] and env["virtuoso"] else "#c62828")
        threading.Thread(target=work, daemon=True).start()

    # ---------------- 操作
    def do_lookup(self) -> None:
        lib, cell = self.src_lib.get().strip(), self.src_cell.get().strip()
        self._append(f"查找 {lib}/{cell} …")

        def work():
            r = core.lookup(lib, cell)
            self._append(("✅ 找到：" + r["path"]) if r["found"]
                         else ("❌ 未找到；样例 cell：" + ", ".join(r["sample_cells"])))
        threading.Thread(target=work, daemon=True).start()

    def do_convert(self) -> None:
        set_job("convert")
        params = {"src_lib": self.src_lib.get().strip(), "src_cell": self.src_cell.get().strip(),
                  "src_pdk": PDKS[self.src_pdk.current()][1],
                  "out_lib": self.out_lib.get().strip(), "out_cell": self.out_cell.get().strip(),
                  "tgt_pdk": PDKS[self.tgt_pdk.current()][1]}
        threading.Thread(target=core.job_convert, args=(params,), daemon=True).start()
        self._poll()

    def do_pvt(self) -> None:
        set_job("pvt")
        threading.Thread(target=core.job_pvt, args=({},), daemon=True).start()
        self._poll()

    # ---------------- 轮询
    def _poll(self) -> None:
        job = core.STATE.get("job") or {}
        pct, stage = job.get("pct", 0), job.get("stage", "")
        self.bar["value"] = pct
        self.stage.config(text=f"{stage}  {pct}%")
        logs = job.get("log", [])
        if logs and self.log.get("1.0", "end").count("\n") <= len(logs) + 1:
            self.log.delete("1.0", "end")
            self.log.insert("end", "\n".join(logs))
            self.log.see("end")
        res = job.get("result") or {}
        if res.get("kind") == "pvt":
            self.out_dir = res.get("out_dir")
            self.result.config(text=f"输出目录：{self.out_dir}\n文件：" + ", ".join(res.get("files", [])))
        elif res.get("next"):
            self.result.config(text="下一步：" + "；".join(res["next"]))
        if job.get("status") == "running":
            self.after(600, self._poll)

    def open_out(self) -> None:
        if self.out_dir and Path(self.out_dir).exists():
            os.startfile(self.out_dir)  # noqa: S606
        else:
            messagebox.showinfo("提示", "还没有 PVT 输出目录（先跑一次 PVT 仿真）。")

    def _append(self, msg: str) -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())