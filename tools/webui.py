#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""amigrate Web UI —— 本地网页版迁移向导（Python 标准库，无第三方依赖）。

启动：python tools/webui.py     → http://127.0.0.1:8800

任务：
  convert：源图 → 导出网表 → 查表 → 换器件（当前绑定 OPA_D/13mmrf conv.config）
  pvt    ：生成 45 点 PVT 网表 → VM 跑 Spectre → 回传 → 解析 → 输出到独立文件夹
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SSH = "ic618"
VM_HOME = "/home/IC"
CREATE_NO_WINDOW = 0x08000000
SUBKW = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
SKILL = ROOT / "skill"
PY = sys.executable
WEB_RUNS = ROOT / "runs" / "2026-11-26-webui"

STATE = {"job": None, "lock": threading.Lock()}


def ssh(cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(["ssh", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=8",
                            "-o", "BatchMode=yes", SSH, cmd],
                           capture_output=True, text=True, timeout=timeout, **SUBKW)
        out = p.stdout or ""
        if p.returncode != 0:
            out += p.stderr or ""
        return p.returncode, out
    except subprocess.TimeoutExpired:
        return 124, "ssh timeout"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def clean_lines(text: str) -> list[str]:
    bad = ("Warning:", "Permanently", "added", "(ED25519)", "to the list", "known hosts")
    return [l for l in text.splitlines() if l.strip() and not any(b in l for b in bad)]


def env_info() -> dict:
    rc, out = ssh("hostname; pgrep -f 'dfII/bin/64bit/virtuoso' | head -1; ls ~/Tech 2>/dev/null")
    lines = clean_lines(out)
    vm = rc == 0 and bool(lines)
    virt = len(lines) >= 2 and lines[1].isdigit()
    pdks = lines[2:] if len(lines) > 2 else []
    rc2, libs = ssh("grep -h '^DEFINE' ~/cds.lib | awk '{print $2}'")
    libraries = [l for l in clean_lines(libs)]
    return {"vm": vm, "virtuoso": virt, "pdks": pdks, "libraries": libraries,
            "host": lines[0] if lines else ""}


def lookup(lib: str, cell: str) -> dict:
    rc, out = ssh(f"ls -d {VM_HOME}/{lib}/{cell}/schematic 2>/dev/null; "
                  f"ls {VM_HOME}/{lib} 2>/dev/null | head -5")
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    found = bool(lines) and lines[0].endswith("schematic")
    return {"found": found, "path": lines[0] if lines else "",
            "sample_cells": lines[1:6] if found else lines[:5]}


def job_log(msg: str) -> None:
    job = STATE["job"]
    if job:
        with STATE["lock"]:
            job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            job["log"] = job["log"][-400:]


def set_stage(name: str, pct: int) -> None:
    job = STATE["job"]
    if not job:
        return
    with STATE["lock"]:
        job["stage"] = name
        job["pct"] = max(job.get("pct", 0), pct)
        if not any(s["name"] == name for s in job["stages"]):
            job["stages"].append({"name": name, "pct": pct})


def run_local(args: list[str], timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, **SUBKW)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------- 任务：转换
def job_convert(params: dict) -> None:
    try:
        set_stage("环境检查", 5)
        env = env_info()
        if not env["vm"] or not env["virtuoso"]:
            raise RuntimeError("VM 或 Virtuoso 未运行，请先启动 Virtuoso")
        job_log("环境 OK（VM 在线、Virtuoso 运行中）")

        set_stage("查找源原理图", 15)
        lk = lookup(params["src_lib"], params["src_cell"])
        if not lk["found"]:
            raise RuntimeError(f"未找到 {params['src_lib']}/{params['src_cell']}/schematic")
        job_log(f"找到：{lk['path']}")

        set_stage("检查目标 PDK 器件表", 30)
        lut_hint = {
            "PDK_13mmrf_1P6M_30k": "runs/2026-11-25-lut-build/13mmrf_io18/lut_13mmrf_io18.csv",
            "smic18ee_2P6M_20100810": "runs/2026-11-25-lut-build/smic18ee/lut_smic18ee.csv",
        }.get(params["tgt_pdk"])
        if lut_hint and not (ROOT / lut_hint).exists():
            raise RuntimeError(f"缺目标表 {lut_hint}，请先 amigrate table")
        job_log("器件表检查通过")

        set_stage("导出源网表（SKILL）", 55)
        rc, out = run_skill("export_netlist.il")
        job_log((clean_lines(out)[-1] if clean_lines(out) else "export 完成"))

        set_stage("生成目标原理图（换器件）", 80)
        rc, out = run_skill("pilot_run.il")
        job_log((clean_lines(out)[-1] if clean_lines(out) else "pilot_run 完成"))

        set_stage("完成", 100)
        with STATE["lock"]:
            STATE["job"]["status"] = "done"
            STATE["job"]["result"] = {
                "kind": "convert",
                "src": f"{params['src_lib']}/{params['src_cell']}",
                "tgt": f"{params['out_lib']}/{params['out_cell']}",
                "next": ["python tools/amigrate.py solve", "python tools/amigrate.py pvt"],
            }
        job_log("✅ 结构迁移完成")
    except Exception as e:  # noqa: BLE001
        with STATE["lock"]:
            STATE["job"]["status"] = "error"
        job_log(f"❌ 失败：{e}")


def run_skill(script: str, timeout: int = 240) -> tuple[int, str]:
    local = SKILL / script
    if not local.exists():
        return 1, f"脚本不存在：{local}"
    subprocess.run(["scp", str(local), f"{SSH}:/tmp/{script}"],
                   capture_output=True, text=True, timeout=60, **SUBKW)
    cmd = (f"cd /tmp && sed -i '1s/^\\xEF\\xBB\\xBF//' {script}; sed -i 's/\\r$//' {script}; "
           f"cd {VM_HOME} && timeout {timeout} virtuoso -nograph < /tmp/{script} > /tmp/{script}.log 2>&1; "
           f"echo EXIT=$?; tail -6 /tmp/{script}.log")
    return ssh(cmd, timeout=timeout + 90)


# ---------------------------------------------------------------- 任务：PVT
def job_pvt(_params: dict) -> None:
    try:
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_dir = WEB_RUNS / f"pvt-{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)
        job_log(f"输出目录：{out_dir}")

        set_stage("生成 45 点 PVT 网表", 8)
        rc, out = run_local([PY, "tools/pvt_sweep.py", "--gen"], timeout=300)
        if rc != 0:
            raise RuntimeError(f"生成网表失败：{out[-300:]}")
        job_log(out.strip().splitlines()[-1] if out.strip() else "网表已生成")

        set_stage("上传到 VM", 18)
        ssh("rm -rf /tmp/pvt; mkdir -p /tmp/pvt")
        for src, dst in [(ROOT / "runs/2026-11-25-pvt/nets", "/tmp/pvt/"),
                         (ROOT / "runs/2026-11-25-pvt/run_pvt.sh", "/tmp/pvt/")]:
            p = subprocess.run(["scp", "-r", str(src), f"{SSH}:{dst}"],
                               capture_output=True, text=True, timeout=300, **SUBKW)
            if p.returncode != 0:
                raise RuntimeError(f"scp 失败：{p.stderr}")
        ssh("sed -i 's/\\r$//' /tmp/pvt/run_pvt.sh")
        job_log("网表与脚本已上传")

        set_stage("运行 Spectre（45 工况 × 2）", 45)
        rc, out = ssh("bash /tmp/pvt/run_pvt.sh > /tmp/pvt/run.log 2>&1; "
                      "grep -c 'EXIT=0' /tmp/pvt/run.log", timeout=1500)
        job_log(f"完成工况数：{clean_lines(out)[-1] if clean_lines(out) else '?'}")

        set_stage("回传结果", 70)
        rc, out = ssh("cd /tmp/pvt && tar czf /tmp/pvt_raw.tgz raw", timeout=180)
        tgz = out_dir / "pvt_raw.tgz"
        p = subprocess.run(["scp", f"{SSH}:/tmp/pvt_raw.tgz", str(tgz)],
                           capture_output=True, text=True, timeout=300, **SUBKW)
        if p.returncode != 0:
            raise RuntimeError(f"回传失败：{p.stderr}")
        with tarfile.open(tgz) as tf:
            tf.extractall(out_dir, filter="data")
        job_log(f"回传完成：{tgz.name}")

        set_stage("解析与汇总", 88)
        rc, out = run_local([PY, "tools/pvt_sweep.py", "--parse",
                             "--raw", str(out_dir / "raw")], timeout=600)
        if rc != 0:
            raise RuntimeError(f"解析失败：{out[-400:]}")
        summary = out.strip().splitlines()
        for line in summary[-8:]:
            job_log(line)

        # 拷贝生成物到输出目录，并写 result.json
        for name in ("pvt.csv", "README.md"):
            src = ROOT / "runs/2026-11-25-pvt" / name
            if src.exists():
                shutil.copy2(src, out_dir / name)
        files = sorted(p.name for p in out_dir.iterdir())
        with (out_dir / "result.json").open("w", encoding="utf-8") as f:
            json.dump({"design": "OPA_D", "corner_count": 45, "out_dir": str(out_dir),
                       "files": files}, f, ensure_ascii=False, indent=2)

        set_stage("完成", 100)
        with STATE["lock"]:
            STATE["job"]["status"] = "done"
            STATE["job"]["result"] = {
                "kind": "pvt", "out_dir": str(out_dir), "files": files,
                "files_url": [f"/files?path={out_dir.relative_to(ROOT).as_posix()}/{x}" for x in files],
            }
        job_log(f"✅ PVT 完成：{out_dir}")
        job_log("文件：" + ", ".join(files))
    except Exception as e:  # noqa: BLE001
        with STATE["lock"]:
            STATE["job"]["status"] = "error"
        job_log(f"❌ 失败：{e}")


def job_generic(params: dict) -> None:
    """通用迁移：发现 PDK → 建表 → 源约束 → 反解 → SKILL 脚本（流式进度）。"""
    try:
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_dir = WEB_RUNS / f"generic-{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)
        job_log(f"输出目录：{out_dir}")
        cmd = [PY, "tools/generic_flow.py",
               "--src-lib", params.get("src_lib", "weekfour_last"),
               "--src-cell", params.get("src_cell", "OPA_D"),
               "--src-net", params.get("src_net", "runs/2026-11-25-io18-ac/src_net.scs"),
               "--tgt-pdk", params.get("tgt_pdk", "PDK_13mmrf_1P6M_30k"),
               "--out", str(out_dir)]
        if params.get("n_dev"):
            cmd += ["--n-dev", params["n_dev"]]
        if params.get("p_dev"):
            cmd += ["--p-dev", params["p_dev"]]
        if params.get("quick"):
            cfg = ROOT / "runs/2026-11-27-generic/discover/PDK_13mmrf_1P6M_30k.json"
            lut = ROOT / "runs/2026-11-27-generic/lut-pilot/lut_PDK_13mmrf_1P6M_30k.csv"
            cons = ROOT / "runs/2026-11-27-generic/constraints/constraints.csv"
            if cfg.exists():
                cmd += ["--cfg", str(cfg)]
            if lut.exists():
                cmd += ["--lut", str(lut)]
            if cons.exists():
                cmd += ["--constraints", str(cons)]

        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", **SUBKW)
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            job_log(line)
            m = re.match(r"STAGE (\d+)/5", line)
            if m:
                i = int(m.group(1))
                set_stage(f"阶段 {i}/5", 10 + i * 17)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"generic_flow 退出码 {rc}")
        files = sorted(p.name for p in out_dir.iterdir())
        summary = {}
        sj = out_dir / "summary.json"
        if sj.exists():
            summary = json.loads(sj.read_text(encoding="utf-8"))
        set_stage("完成", 100)
        with STATE["lock"]:
            STATE["job"]["status"] = "done"
            STATE["job"]["result"] = {
                "kind": "generic", "out_dir": str(out_dir), "files": files,
                "sizes": summary.get("sizes"), "skill": summary.get("skill"),
                "solved": summary.get("solved"),
                "files_url": [f"/files?path={out_dir.relative_to(ROOT).as_posix()}/{x}" for x in files],
            }
        job_log(f"✅ 通用迁移完成：{summary.get('solved', '?')} 个器件")
    except Exception as e:  # noqa: BLE001
        with STATE["lock"]:
            STATE["job"]["status"] = "error"
        job_log(f"❌ 失败：{e}")


WORKERS = {"convert": job_convert, "pvt": job_pvt, "generic": job_generic}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if u.path == "/api/env":
            self._send(200, json.dumps(env_info(), ensure_ascii=False).encode())
            return
        if u.path == "/api/lookup":
            q = parse_qs(u.query)
            self._send(200, json.dumps(lookup(q.get("lib", [""])[0], q.get("cell", [""])[0]),
                                       ensure_ascii=False).encode())
            return
        if u.path == "/api/job":
            with STATE["lock"]:
                job = STATE["job"]
            self._send(200, json.dumps(job or {"status": "idle", "log": [], "pct": 0,
                                               "stages": []}, ensure_ascii=False).encode())
            return
        if u.path.startswith("/assets/"):
            p = (ROOT / u.path.lstrip("/")).resolve()
            if str(p).startswith(str(ROOT / "assets")) and p.is_file():
                self._send(200, p.read_bytes(), "image/png")
                return
        if u.path == "/files":
            q = parse_qs(u.query)
            rel = unquote(q.get("path", [""])[0])
            p = (ROOT / rel).resolve()
            if not str(p).startswith(str(ROOT)) or not p.is_file():
                self._send(404, b"not found")
                return
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/start":
            kind = body.get("kind", "convert")
            if kind not in WORKERS:
                self._send(400, b'{"error":"bad kind"}')
                return
            with STATE["lock"]:
                if STATE["job"] and STATE["job"]["status"] == "running":
                    self._send(409, b'{"error":"job running"}')
                    return
                STATE["job"] = {"id": str(int(time.time())), "kind": kind, "status": "running",
                                "log": [], "result": {}, "pct": 0, "stage": "启动", "stages": []}
            threading.Thread(target=WORKERS[kind], args=(body,), daemon=True).start()
            self._send(200, b'{"ok":true}')
            return
        self._send(404, b'{"error":"not found"}')

    def log_message(self, *a):  # 安静
        pass


HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>amigrate · 模拟电路迁移向导</title>
<link rel="icon" href="/assets/icon.png">
<style>
:root{--ink:#1b2233;--muted:#5b6478;--line:#e3e7ef;--bg:#f6f8fb;--card:#fff;--ok:#178a4c;--bad:#c62828;--brand:#1f3864}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:22px}
header{background:var(--brand);color:#fff;border-radius:12px;padding:18px 22px;margin-bottom:14px}
h1{margin:0;font-size:20px}h2{font-size:14px;margin:0 0 10px;color:var(--brand)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.row{display:flex;gap:14px;flex-wrap:wrap}.row>div{flex:1;min-width:190px}
label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
input,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fff}
button{padding:9px 16px;border:0;border-radius:8px;background:var(--brand);color:#fff;font:inherit;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;border:1px solid}
.ok{color:var(--ok);border-color:#bfe3cf;background:#f0fbf4}.bad{color:var(--bad);border-color:#f1c7c7;background:#fff4f4}
.muted{color:var(--muted);font-size:12px}
pre{background:#0f172a;color:#d7e2f1;padding:12px;border-radius:8px;max-height:300px;overflow:auto;font-size:12px}
.bar{height:10px;background:#e8edf6;border-radius:999px;overflow:hidden;margin:8px 0 6px}
.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#2a9d8f,#1f3864);transition:width .4s}
.hide{display:none}ul{padding-left:18px;margin:6px 0}
</style></head><body><div class="wrap">
<header><h1>amigrate · 模拟电路迁移向导</h1>
<div class="muted" style="color:#c9d6ea">SMIC18 ↔ SMIC13（可扩展）· 本地网页 · 后台调用 VM 的 Virtuoso/Spectre</div></header>

<div class="card"><h2>0. 环境检测</h2>
<div id="envline" class="muted">检测中…</div>
<div style="margin-top:10px"><button id="retry">重新检测</button></div></div>

<div class="card hide" id="form1"><h2>1. 源设计</h2>
<div class="row">
<div><label>源库</label><input id="src_lib" value="weekfour_last"></div>
<div><label>原理图名</label><input id="src_cell" value="OPA_D"></div>
<div><label>源 PDK</label><select id="src_pdk">
<option value="smic18ee_2P6M_20100810">SMIC18（smic18ee）</option>
<option value="PDK_13mmrf_1P6M_30k">SMIC13（13mmrf）</option>
<option value="__custom__">其他（手动输入）</option></select></div>
</div>
<div class="row" id="src_custom" style="margin-top:8px;display:none">
<div><label>自定义源 PDK</label><input id="src_pdk_custom" placeholder="例如 xfab_xt018"></div></div>
<div style="margin-top:12px"><button id="find">查找原理图</button> <span id="findres" class="muted"></span></div>
</div>

<div class="card hide" id="form2"><h2>2. 目标设计</h2>
<div class="row">
<div><label>输出库</label><input id="out_lib" value="port_pilot"></div>
<div><label>输出原理图名</label><input id="out_cell" value="OPA_D_13mmrf"></div>
<div><label>目标 PDK</label><select id="tgt_pdk">
<option value="PDK_13mmrf_1P6M_30k">SMIC13（13mmrf）</option>
<option value="smic18ee_2P6M_20100810">SMIC18（smic18ee）</option>
<option value="__custom__">其他（手动输入）</option></select></div>
</div>
<div class="row" id="tgt_custom" style="margin-top:8px;display:none">
<div><label>自定义目标 PDK</label><input id="tgt_pdk_custom" placeholder="例如 xfab_xt018"></div></div>
<div style="margin-top:12px"><button id="start">开始迁移</button> <span class="muted">导出网表 → 查表 → 换器件</span></div>
</div>

<div class="card hide" id="pvtcard"><h2>3. PVT 仿真（45 点）→ 输出到独立文件夹</h2>
<button id="pvt">开始 PVT 仿真</button>
<span class="muted">生成网表 → VM 跑 Spectre → 回传 → 解析，结果保存到 runs/2026-11-26-webui/pvt-&lt;时间戳&gt;/</span>
</div>

<div class="card hide" id="gencard"><h2>4. 通用迁移（其他 PDK）</h2>
<div class="row">
<div><label>源网表</label><input id="g_net" value="runs/2026-11-25-io18-ac/src_net.scs"></div>
<div><label>目标 PDK（Tech 目录名）</label><input id="g_pdk" value="PDK_13mmrf_1P6M_30k"></div>
<div><label>n 器件（可选）</label><input id="g_ndev" placeholder="n33_mis_ckt"></div>
<div><label>p 器件（可选）</label><input id="g_pdev" placeholder="p33_mis_ckt"></div>
</div>
<div style="margin-top:10px">
<label style="display:inline;color:var(--muted)"><input type="checkbox" id="g_quick" checked style="width:auto"> 快速验证（复用已有 13mmrf 中间结果，跳过建表）</label>
</div>
<div style="margin-top:10px"><button id="generic">开始通用迁移</button>
<span class="muted">发现 PDK → 建表 → 源约束 → 反解尺寸 → 生成 SKILL 脚本</span></div>
</div>

<div class="card hide" id="logcard"><h2>进度</h2>
<div class="bar"><i id="bar"></i></div>
<div class="muted" id="stage">准备中…</div>
<pre id="log"></pre>
<div id="result" class="muted" style="margin-top:8px"></div></div>

<script>
const $=s=>document.querySelector(s);
async function env(){ const r=await fetch('/api/env'); const d=await r.json();
  let h = d.vm?'<span class="pill ok">VM 在线</span> ':'<span class="pill bad">VM 不可达</span> ';
  h += d.virtuoso?'<span class="pill ok">Virtuoso 运行中</span> ':'<span class="pill bad">Virtuoso 未运行</span> ';
  h += '<span class="muted">PDK：'+(d.pdks||[]).join(' / ')+'</span>';
  if(!d.vm||!d.virtuoso) h += '<div style="margin-top:8px" class="muted">请先在 VM 启动 Virtuoso 后点“重新检测”。</div>';
  $('#envline').innerHTML=h;
  if(d.vm&&d.virtuoso){ $('#form1').classList.remove('hide'); $('#pvtcard').classList.remove('hide'); $('#gencard').classList.remove('hide'); }
}
$('#retry').onclick=env;
$('#src_pdk').onchange=e=>{$('#src_custom').style.display=e.target.value==='__custom__'?'flex':'none'};
$('#tgt_pdk').onchange=e=>{$('#tgt_custom').style.display=e.target.value==='__custom__'?'flex':'none'};
$('#find').onclick=async()=>{ const lib=$('#src_lib').value, cell=$('#src_cell').value;
  $('#findres').textContent='查找中…';
  const d=await (await fetch('/api/lookup?lib='+encodeURIComponent(lib)+'&cell='+encodeURIComponent(cell))).json();
  if(d.found){ $('#findres').innerHTML='<span class="pill ok">找到</span> '+d.path; $('#form2').classList.remove('hide'); }
  else $('#findres').innerHTML='<span class="pill bad">未找到</span> 样例：'+(d.sample_cells||[]).join(', ');
};
async function start(kind, payload){ $('#logcard').classList.remove('hide');
  const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({kind,...payload})});
  if(!r.ok){ $('#log').textContent='启动失败：'+(await r.text()); return; }
  poll();
}
$('#start').onclick=()=>start('convert',{src_lib:$('#src_lib').value,src_cell:$('#src_cell').value,
  src_pdk:$('#src_pdk').value,out_lib:$('#out_lib').value,out_cell:$('#out_cell').value,
  tgt_pdk:$('#tgt_pdk').value});
$('#pvt').onclick=()=>start('pvt',{});
$('#generic').onclick=()=>start('generic',{src_net:$('#g_net').value,tgt_pdk:$('#g_pdk').value,n_dev:$('#g_ndev').value,p_dev:$('#g_pdev').value,quick:$('#g_quick').checked});
async function poll(){ const d=await (await fetch('/api/job')).json();
  $('#bar').style.width=(d.pct||0)+'%';
  $('#stage').textContent=(d.stage||'')+'  '+(d.pct||0)+'%';
  $('#log').textContent=(d.log||[]).join('\\n');
  if(d.result&&d.result.kind==='pvt'){
    let h='<b>输出目录：</b>'+d.result.out_dir+'<br><b>文件：</b><ul>';
    (d.result.files||[]).forEach((f,i)=>{ h+='<li><a href="'+d.result.files_url[i]+'">'+f+'</a></li>'; });
    $('#result').innerHTML=h+'</ul>';
  } else if(d.result&&d.result.next){
    $('#result').innerHTML='下一步：<br>'+d.result.next.map(x=>'· '+x).join('<br>');
  }
  if(d.status==='running') setTimeout(poll,1500);
}
env();
</script></div></body></html>"""


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    port = 8800
    if port_in_use(port):
        print(f"端口 {port} 已有服务在运行，直接打开页面。")
        import webbrowser
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:  # noqa: BLE001
            pass
        return 0
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"amigrate Web UI → http://127.0.0.1:{port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())