# -*- coding: utf-8 -*-
"""
git 封装层：EasyGit 与 git 唯一的对话通道（技术选型定案：直接调 git CLI）。

设计依据：需求文档 第二章「扩展性落地机制」——
  * 只返回结构化数据（dataclass），UI 层永不解析 git 原始输出；
  * 新 git 能力 = 在 GitRepo 上加一个方法。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ================= 数据结构（UI 层只消费这些） =================

@dataclass
class CommandRecord:
    """一次 git 命令的执行记录（统一执行管道的最小单元，也是命令预览栏的数据源）"""
    cmd: str            # 完整命令文本，如 "git status --porcelain=v1 -b"
    ok: bool            # 退出码 == 0
    output: str = ""    # stdout；失败时 stderr 也并进来
    time: str = ""      # 执行时刻
    show_output: bool = False   # 日志面板是否回显输出（内嵌命令行用 True）

    def __post_init__(self) -> None:
        if not self.time:
            self.time = datetime.now().strftime("%H:%M:%S")


@dataclass
class GitFile:
    """状态面板里的一个文件"""
    path: str
    x: str              # 暂存区状态（porcelain 第 1 列）
    y: str              # 工作区状态（porcelain 第 2 列）

    @property
    def group(self) -> str:
        """分组依据，对应需求文档「状态面板分组规格」。
        v0.1 先实现四个基本组；已退库/仅本地/被忽略分组在后续里程碑接入。"""
        if "U" in self.x + self.y or (self.x == self.y == "A") or (self.x == self.y == "D"):
            return "conflict"     # 冲突中
        if self.x == "?" and self.y == "?":
            return "untracked"    # 未跟踪
        if self.x == "!" and self.y == "!":
            return "ignored"      # 被忽略
        if self.x not in (" ", "?", "!"):
            return "staged"       # 已勾选、将提交
        return "unstaged"         # 改了、未勾选


@dataclass
class BranchInfo:
    """工具栏要显示的分支状态（设计原则：一切状态可见）"""
    name: str = ""                       # 当前分支名
    detached: bool = False              # HEAD 游离（提示条触发条件之一）
    upstream: Optional[str] = None       # 跟踪的远端分支，如 "origin/main"
    ahead: int = 0                       # 领先远端多少个提交
    behind: int = 0                      # 落后远端多少个提交


@dataclass
class StatusInfo:
    """一次 git status 的完整结构化结果"""
    branch: BranchInfo = field(default_factory=BranchInfo)
    files: list[GitFile] = field(default_factory=list)


@dataclass
class Commit:
    """历史树上的一个提交"""
    hash: str
    short: str
    parents: list[str] = field(default_factory=list)
    author: str = ""
    date_rel: str = ""       # 相对时间，如 "2 hours ago"
    subject: str = ""        # 提交消息首行
    refs: list[str] = field(default_factory=list)   # 如 ["HEAD -> main", "origin/main"]
    # —— 泳道图布局字段（由 history_layout.assign_lanes 就地填充）——
    lane: int = 0
    lanes_above: list[int] = field(default_factory=list)
    lanes_below: list[int] = field(default_factory=list)
    merge_edges: list[tuple[int, int]] = field(default_factory=list)
    fork_edges: list[tuple[int, int]] = field(default_factory=list)


# ================= 封装层本体 =================

class GitRepo:
    """
    一个已打开的仓库。所有 git 能力都以方法挂在这里：
    增删功能时本类的既有方法【不需要】改动（易扩展总纲）。
    """

    def __init__(self, path: str, log=None):
        """
        path: 仓库根目录
        log:  可选的 CommandLog，所有命令都会记入（统一执行管道）
        """
        self.path = path
        self._log = log

    # ---- 底座：所有命令都经过它（统一执行管道的入口） ----
    def run_git(self, args: list[str]) -> CommandRecord:
        cmd = "git " + " ".join(args)
        try:
            proc = subprocess.run(
                ["git", "-c", "core.quotepath=false", *args],
                cwd=self.path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except OSError as exc:
            rec = CommandRecord(cmd=cmd, ok=False, output=f"无法启动 git：{exc}")
            self._log and self._log.add(rec)
            return rec
        output = proc.stdout
        if proc.returncode != 0:
            output = (proc.stdout + "\n" + proc.stderr).strip()
        rec = CommandRecord(cmd=cmd, ok=proc.returncode == 0, output=output)
        self._log and self._log.add(rec)
        return rec

    # ---- 能力 1：状态（v1 #1 改动页的数据源） ----
    def status(self) -> StatusInfo:
        """git status 的结构化版本"""
        info = StatusInfo()
        rec = self.run_git(["status", "--porcelain=v1", "-b"])
        if not rec.ok:
            return info
        for line in rec.output.splitlines():
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("##"):
                info.branch = _parse_branch_line(line[2:].strip())
                continue
            if len(line) < 4:
                continue
            x, y, rest = line[0], line[1], line[3:]
            # 重命名形如 "R  新路径 -> 旧路径"，只留新路径
            path = rest.split(" -> ")[-1] if " -> " in rest else rest
            info.files.append(GitFile(path=path, x=x, y=y))
        return info


    # ---- 能力 2：勾选即提交（v1 #2：暂存只在幕后，命令栏照实显示） ----
    def stage(self, paths: list[str]) -> CommandRecord:
        """勾上 = 进入下次提交（幕后即 git add）"""
        return self.run_git(["add", "--", *paths])

    def unstage(self, paths: list[str]) -> CommandRecord:
        """取消勾选 = 从下次提交里拿出来（幕后即 git restore --staged）"""
        return self.run_git(["restore", "--staged", "--", *paths])

    # ---- 能力 3：提交 ----
    def commit(self, message: str) -> CommandRecord:
        """提交已勾选的改动（幕后即 git commit -m）"""
        return self.run_git(["commit", "-m", message])


    # ---- 能力 4：提交历史（v1 #5 数据源） ----
    def log(self, skip: int = 0, limit: int = 50) -> list[Commit]:
        """按时间倒序返回提交；泳道布局由 history_layout 负责"""
        fmt = "%H%x1f%h%x1f%P%x1f%an%x1f%ar%x1f%s%x1f%d"
        rec = self.run_git([
            "log", "--topo-order", f"--skip={skip}", "-n", str(limit),
            f"--pretty=format:{fmt}",
        ])
        if not rec.ok:
            return []
        commits: list[Commit] = []
        for line in rec.output.splitlines():
            parts = line.split("\x1f")
            if len(parts) < 6:
                continue
            h, short, parents, author, date_rel, subject = parts[:6]
            refs_raw = parts[6].strip() if len(parts) > 6 else ""
            refs = [r.strip() for r in refs_raw.strip("()").split(",") if r.strip()]
            commits.append(Commit(
                hash=h, short=short,
                parents=[p for p in parents.split() if p],
                author=author, date_rel=date_rel,
                subject=subject, refs=refs,
            ))
        return commits

    def commit_files(self, commit_hash: str) -> list[tuple[str, str]]:
        """某次提交改动的文件清单 [(状态, 路径)]（合并提交用 -m 展开比较）"""
        rec = self.run_git(["diff-tree", "--no-commit-id", "--name-status",
                            "-r", "-m", commit_hash])
        if not rec.ok:
            return []
        files: list[tuple[str, str]] = []
        for line in rec.output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                files.append((parts[0].strip(), parts[-1]))
        return files

    def commit_diff(self, commit_hash: str, path: str) -> str:
        """某次提交中某文件的 diff 文本（纯文本，彩色版归 diff 查看器里程碑）。
        合并提交用 --first-parent：看它给主线带来了什么
        （组合 diff 常为空，不适合阅读）"""
        rec = self.run_git(["show", "--first-parent", "--format=", commit_hash, "--", path])
        if not rec.ok:
            return f"（无法读取 diff）{rec.output.splitlines()[0] if rec.output else ''}"
        return rec.output

    # ---- 能力 5：单文件 diff（v1 #1「点文件名看 diff」的数据源） ----
    def file_diff_head(self, path: str) -> str:
        """工作区+已勾选内容 vs HEAD 的单文件差异；空仓库时返回空串"""
        rec = self.run_git(["diff", "HEAD", "--", path])
        if not rec.ok:
            return ""    # 空仓库（还没有任何提交）时 HEAD 不存在
        return rec.output


def _parse_branch_line(text: str) -> BranchInfo:
    """解析 '## main...origin/main [ahead 2, behind 1]' 这类行"""
    b = BranchInfo()
    if text.startswith("HEAD (no branch)"):
        b.detached = True
        return b
    if "..." in text:
        head, tail = text.split("...", 1)
        b.name = head.strip()
        if tail.startswith("("):
            b.detached = True
            return b
        b.upstream = tail.split("[", 1)[0].strip() or None
        if "[" in tail:
            for part in tail.split("[", 1)[1].rstrip("]").split(", "):
                part = part.strip()
                if part.startswith("ahead"):
                    b.ahead = int(part.split()[-1])
                elif part.startswith("behind"):
                    b.behind = int(part.split()[-1])
    else:
        # "## main" 或 "## No commits yet on main"
        b.name = text.split()[-1] if text else ""
    return b
