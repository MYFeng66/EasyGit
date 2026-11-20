# -*- coding: utf-8 -*-
"""内嵌命令行（v1 #8 的内嵌形态，2026-11-20 用户标定：不再弹外部终端）。

后端优先级：**Git Bash**（真 Unix 语法，ls/cat/grep/管道全部可用，
git 教程里的命令照抄就能跑）→ PowerShell → cmd。纯 Python，无界面依赖。"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .git_wrapper import CommandRecord

_BACKEND: str | None = None
_BASH_PATH: str | None = None


def _detect_backend() -> tuple[str, str | None]:
    """找 Git Bash：随 Git for Windows 安装，从 git.exe 的位置反推。
    注意不能直接 which('bash')——Windows 的 System32\\bash.exe 是 WSL 入口，
    那是 Linux 环境（git 都不一定装），语义完全不同。"""
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent   # ...\Git\cmd\git.exe → ...\Git
        for sub in ("bin", "usr/bin"):
            cand = root / sub / "bash.exe"
            if cand.exists():
                return "bash", str(cand)
    if shutil.which("powershell"):
        return "powershell", None
    return "cmd", None


def _backend() -> tuple[str, str | None]:
    global _BACKEND, _BASH_PATH
    if _BACKEND is None:
        _BACKEND, _BASH_PATH = _detect_backend()
    return _BACKEND, _BASH_PATH


def run_shell(cwd: str, text: str, timeout: int = 120) -> CommandRecord:
    """在 cwd 执行命令文本；返回 CommandRecord（输出回显到日志面板）。

    * 非交互命令适用（git / ls / cat / grep / pip / python ...）
    * 交互式程序（vim、ssh 密码）不支持 → 点工具栏「外部终端」
    * 每条命令都在仓库根目录执行（cd 不持久）
    """
    rec = CommandRecord(cmd=f"$ {text}", ok=False,
                        time=datetime.now().strftime("%H:%M:%S"))
    kind, bash_path = _backend()

    if kind == "bash":
        argv = [bash_path, "-c", text]
    elif kind == "powershell":
        argv = ["powershell", "-NoProfile", "-Command",
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                + text + "; exit $LASTEXITCODE"]
    else:
        argv = ["cmd", "/c", text]

    # git 中文路径默认八进制转义（\350\256\241... 这种），用环境变量机制强制可读
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "core.quotepath"
    env["GIT_CONFIG_VALUE_0"] = "false"

    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        rec.output = f"命令超时（>{timeout} 秒）"
        return rec
    except OSError as exc:
        rec.output = f"无法执行：{exc}"
        return rec

    raw = proc.stdout or b""
    if proc.stderr:
        raw += b"\n" + proc.stderr
    try:
        out = raw.decode("utf-8")
    except UnicodeDecodeError:
        out = raw.decode("gbk", errors="replace")
    rec.output = out.strip()
    rec.ok = proc.returncode == 0
    rec.show_output = True      # 用户手敲的命令：输出回显到日志面板
    return rec
