# -*- coding: utf-8 -*-
"""
git 封装层：EasyGit 与 git 唯一的对话通道（技术选型定案：直接调 git CLI）。

设计依据：需求文档 第二章「扩展性落地机制」——
  * 只返回结构化数据（dataclass），UI 层永不解析 git 原始输出；
  * 新 git 能力 = 在 GitRepo 上加一个方法。
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
    ok: bool = True          # git status 是否执行成功（失败时 files 为空但不可当成“干净”）
    error: str = ""          # 失败原因首行


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


@dataclass
class BranchEntry:
    """分支页里的一条分支"""
    name: str
    upstream: str = ""          # 跟踪的远端分支，如 "origin/main"
    is_head: bool = False        # 是否当前分支
    is_remote: bool = False      # 是否远端分支（origin/xxx）


@dataclass
class StashEntry:
    """储藏（stash）里的一条存档"""
    ref: str          # stash@{0}
    message: str      # On master: EasyGit：切换到 xxx 前自动暂存


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
        """git status 的结构化版本。
        失败（如 index.lock 被并发 git 进程占用）时 ok=False、files 为空；
        对 index.lock 重试一次，避开瞬时冲突。"""
        info = StatusInfo()
        rec = self.run_git(["status", "--porcelain=v1", "-b"])
        if not rec.ok and "index.lock" in rec.output:
            time.sleep(0.4)                    # 等并发进程放锁，重试一次
            rec = self.run_git(["status", "--porcelain=v1", "-b"])
        if not rec.ok:
            info.ok = False
            info.error = rec.output.splitlines()[0] if rec.output else "git status 执行失败"
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

    # ---- 能力 6：撤销三件套（v1 #2 后半，痛点 C） ----
    def is_head_pushed(self) -> bool:
        """HEAD 是否已出现在某条远端分支上（决定撤销还是反提交）"""
        rec = self.run_git(["branch", "-r", "--contains", "HEAD"])
        return bool(rec.ok and rec.output.strip())

    def undo_last_commit(self) -> CommandRecord:
        """撤销上次提交，改动保留在「已勾选」里（幕后 git reset --soft HEAD~1）"""
        return self.run_git(["reset", "--soft", "HEAD~1"])

    def revert_last_commit(self) -> CommandRecord:
        """反提交抵消上次提交：产生新提交而非删历史（幕后 git revert --no-edit HEAD）"""
        return self.run_git(["revert", "--no-edit", "HEAD"])

    # ---- 能力 7：远程同步与分支（v1 #3/#4） ----
    def has_remote(self) -> bool:
        rec = self.run_git(["remote"])
        return bool(rec.ok and rec.output.strip())

    def fetch(self) -> CommandRecord:
        """取件：只更新远端记账副本，不动工作区（第七章 2：自动执行）"""
        return self.run_git(["fetch", "--all"])

    def pull(self) -> CommandRecord:
        """拉取 = fetch + 合并进当前分支；永远手动（动工作区的操作必须守卫）"""
        return self.run_git(["pull", "--no-edit"])

    def push(self) -> CommandRecord:
        return self.run_git(["push"])

    def push_set_upstream(self, branch: str | None = None) -> CommandRecord:
        """建立上游关联并推送（E 类痛点一键化；branch=None 即当前分支）"""
        return self.run_git(["push", "-u", "origin", branch or "HEAD"])

    def branches(self) -> tuple[list[BranchEntry], list[BranchEntry]]:
        """(本地分支, 远端分支)；本地条目带 upstream 与 is_head 标记"""
        loc: list[BranchEntry] = []
        rem: list[BranchEntry] = []
        fmt = "--format=%(refname:short)%09%(upstream:short)%09%(HEAD)"
        r1 = self.run_git(["for-each-ref", fmt, "refs/heads"])
        if r1.ok:
            for line in r1.output.splitlines():
                parts = line.split("\t")
                if not parts or not parts[0].strip():
                    continue
                loc.append(BranchEntry(
                    name=parts[0].strip(),
                    upstream=(parts[1].strip() if len(parts) > 1 else ""),
                    is_head=(len(parts) > 2 and parts[2].strip() == "*"),
                ))
        r2 = self.run_git(["for-each-ref", "--format=%(refname:short)",
                           "refs/remotes"])
        if r2.ok:
            for line in r2.output.splitlines():
                name = line.strip()
                # origin/HEAD 的短名是不带斜杠的 "origin"，不是真分支 → 跳过
                if name and "/" in name:
                    rem.append(BranchEntry(name=name, is_remote=True))
        return loc, rem

    def switch_branch(self, name: str) -> CommandRecord:
        return self.run_git(["switch", name])

    def switch_create(self, new_branch: str, from_ref: str) -> CommandRecord:
        """从远端分支检出新本地分支（origin/feature → 本地 feature）"""
        return self.run_git(["switch", "-c", new_branch, from_ref])

    def delete_branch(self, name: str) -> CommandRecord:
        return self.run_git(["branch", "-d", name])

    def stash_push(self, message: str) -> CommandRecord:
        """切分支守卫的「先暂存」选项（幕后 git stash push）。
        -u 连未跟踪文件一起入储藏——未跟踪文件挡路时，不带 -u 的 stash 根本解决不了。"""
        return self.run_git(["stash", "push", "-u", "-m", message])

    def stash_list(self) -> list[StashEntry]:
        """储藏清单（改动页「储藏…」按钮的数据源）"""
        rec = self.run_git(["stash", "list"])
        entries: list[StashEntry] = []
        if rec.ok:
            for line in rec.output.splitlines():
                if not line.strip():
                    continue
                ref, _, msg = line.partition(":")
                entries.append(StashEntry(ref=ref.strip(), message=msg.strip()))
        return entries

    def stash_pop(self, ref: str) -> CommandRecord:
        """取回储藏：改动放回工作区，并从储藏删除（有冲突时 git 会保留条目）"""
        return self.run_git(["stash", "pop", ref])

    def stash_drop(self, ref: str) -> CommandRecord:
        """丢弃一条储藏（内容真的会丢，界面必须先确认）"""
        return self.run_git(["stash", "drop", ref])

    # ---- 能力 9：仅本地文件（F 类痛点，2026-11-21 用户实战倒逼提前实装）----
    def mark_local(self, paths: list[str]) -> CommandRecord:
        """标记「仅本地」：改动不再显示、不会被提交/推送（幕后 skip-worktree）。
        注意：git 切分支时仍会拒绝覆盖这类文件——需要配合备份/复原五步舞（见 branch_page）。"""
        return self.run_git(["update-index", "--skip-worktree", *paths])

    def unmark_local(self, paths: list[str]) -> CommandRecord:
        """解除「仅本地」标记（五步舞第一步：让 git 正常看见并处理这些文件）"""
        return self.run_git(["update-index", "--no-skip-worktree", *paths])

    def restore_paths(self, paths: list[str]) -> CommandRecord:
        """把文件恢复为当前分支 HEAD 的版本（丢弃本地改动，切换前清障用）"""
        return self.run_git(["restore", "--source=HEAD", "--", *paths])

    def tracked_subset(self, paths: list[str]) -> list[str]:
        """返回这些路径中当前被 git 跟踪的子集（判断挡路文件是跟踪还是未跟踪）"""
        rec = self.run_git(["ls-files", "--", *paths])
        if not rec.ok:
            return []
        return [line.strip() for line in rec.output.splitlines() if line.strip()]

    # ---- 能力 8：冲突与分支对比（v1 #6/#9） ----
    def merge_in_progress(self) -> bool:
        return (Path(self.path) / ".git" / "MERGE_HEAD").exists()

    def unmerged_files(self) -> list[str]:
        rec = self.run_git(["diff", "--name-only", "--diff-filter=U"])
        if not rec.ok:
            return []
        return [line for line in rec.output.splitlines() if line.strip()]

    def conclude_merge(self) -> CommandRecord:
        """冲突向导收尾：一键完成合并提交（幕后 git commit --no-edit）"""
        return self.run_git(["commit", "--no-edit"])

    def compare_branches(self, a: str, b: str) -> list[tuple[str, str]]:
        """两个分支的差异文件清单 [(状态码, 路径)]（A/D/M/R…）"""
        rec = self.run_git(["diff", "--name-status", a, b])
        if not rec.ok:
            return []
        files: list[tuple[str, str]] = []
        for line in rec.output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                files.append((parts[0].strip(), parts[-1]))
        return files

    def branch_diff(self, a: str, b: str, path: str) -> str:
        """两个分支间某文件的 diff 文本"""
        rec = self.run_git(["diff", a, b, "--", path])
        return rec.output if rec.ok else ""

    # ---- 能力 10：版本恢复（历史页右键，2026-11-21 用户需求：HEAD 指向哪个版本）----
    def checkout_detached(self, commit_hash: str) -> CommandRecord:
        """把 HEAD 指到某提交「回到那个版本看看」（detached，不动任何分支，随时可回）"""
        return self.run_git(["switch", "-d", commit_hash])

    def switch_create_at(self, commit_hash: str, new_branch: str) -> CommandRecord:
        """从某个历史版本创建新分支（在旧版本上安全开工）"""
        return self.run_git(["switch", "-c", new_branch, commit_hash])

    def restore_file_from(self, commit_hash: str, path: str) -> CommandRecord:
        """把工作区某文件恢复成指定版本的样子（覆盖未提交改动，界面需确认）"""
        return self.run_git(["restore", "--source", commit_hash, "--", path])


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


def files_blocked_by_switch(output: str) -> list[str]:
    """从 git switch/checkout 的拒绝信息中解析挡路文件清单。
    兼容 tracked（Your local changes…）与 untracked（untracked working tree files…）两种措辞。"""
    files: list[str] = []
    collecting = False
    for line in output.splitlines():
        if "would be overwritten by checkout" in line:
            collecting = True
            continue
        if not collecting:
            continue
        s = line.strip()
        if not s or s.startswith(("Please", "Aborting", "error", "fatal")):
            collecting = False
            continue
        files.append(s)
    return files


def clone_repo(url: str, target: str) -> CommandRecord:
    """把远程仓库克隆到本地目录（添加仓库向导用；不属于任何 GitRepo 实例）。
    克隆进度走 stderr，成功时不回显、失败时显示末行。"""
    cmd = f"git clone {url} {target}"
    try:
        proc = subprocess.run(
            ["git", "clone", url, target],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandRecord(cmd=cmd, ok=False, output=f"克隆失败：{exc}")
    if proc.returncode == 0:
        return CommandRecord(cmd=cmd, ok=True)
    out = (proc.stdout + "\n" + proc.stderr).strip()
    return CommandRecord(cmd=cmd, ok=False, output=out)
