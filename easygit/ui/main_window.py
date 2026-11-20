# -*- coding: utf-8 -*-
"""
主窗口：三区布局（需求文档 第六章）。
左栏仓库列表 ｜ 主区（工具栏 + 提示条 + 页签 + 提交条） ｜ 底部命令预览栏
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import features
from ..core import settings as settings_mod
from ..core.executor import CommandLog, translate_error
from ..core.git_wrapper import CommandRecord, GitRepo, StatusInfo
from ..core.shell import run_shell
from .worker import run_async


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyGit —— 你自己的 Git 管理器")
        self.resize(1080, 720)

        self.settings = settings_mod.load()
        self.log = CommandLog()
        self._workers: list = []        # 活跃后台线程引用（防垃圾回收）
        self.repo: GitRepo | None = None
        self.pages: dict[str, QWidget] = {}
        self._staged_count = 0          # 已勾选、将提交的文件数（驱动提交按钮）
        self._shown_log = 0             # 已写入日志面板的条数
        self._term_cwd = None            # 内嵌终端会话目录（cd 持久，切仓库时重置）

        self._build_ui()
        self._reload_repos()

    # ================================================ 界面搭建
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 工具栏：一切状态可见 ----
        bar = QWidget()
        bar.setObjectName("toolbar")   # 命名选择器：样式只作用于容器本身，不向子控件扩散
        bar.setStyleSheet("QWidget#toolbar{background:#f0f0f0;border-bottom:1px solid #ccc;}")
        bar.setAttribute(Qt.WA_StyledBackground, True)   # 不加此属性背景色不会绘制
        hbar = QHBoxLayout(bar)
        hbar.setContentsMargins(8, 4, 8, 4)
        self.label_branch = QLabel("分支：—")
        self.label_ab = QLabel("")
        self.label_ab.setStyleSheet("color:#1565c0;")
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh_status)
        btn_terminal = QPushButton("外部终端")
        btn_terminal.clicked.connect(self.open_terminal)
        hbar.addWidget(self.label_branch)
        hbar.addWidget(self.label_ab)
        hbar.addWidget(btn_refresh)
        hbar.addStretch(1)
        hbar.addWidget(btn_terminal)
        root.addWidget(bar)

        # ---- 提示条（仅异常时出现，第六章 4） ----
        self.banner = QWidget()
        self.banner.setObjectName("banner")
        self.banner.setStyleSheet("QWidget#banner{background:#fff3cd;border-bottom:1px solid #e0c060;}")
        self.banner.setAttribute(Qt.WA_StyledBackground, True)
        hb = QHBoxLayout(self.banner)
        hb.setContentsMargins(8, 4, 8, 4)
        self.label_banner = QLabel("⚠")
        self.label_banner.setStyleSheet("color:#8a6d00;")
        btn_banner = QPushButton("去处理")
        btn_banner.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        hb.addWidget(self.label_banner)
        hb.addStretch(1)
        hb.addWidget(btn_banner)
        self.banner.hide()
        root.addWidget(self.banner)

        # ---- 中部：左仓库列表 + 右页签 ----
        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        head = QLabel(" 仓库")
        head.setStyleSheet("font-weight:bold;padding:4px;")
        self.list_repo = QListWidget()
        self.list_repo.currentTextChanged.connect(self._select_repo)
        btn_add = QPushButton("+ 添加仓库")
        btn_add.clicked.connect(self.add_repo)
        lv.addWidget(head)
        lv.addWidget(self.list_repo, 1)
        lv.addWidget(btn_add)
        split.addWidget(left)

        # 功能页（features 注册表驱动 —— 加/删功能不动这里）
        self.tabs = QTabWidget()
        for f in features.FEATURES:
            page = f["create"](self)
            self.pages[f["title"]] = page
            self.tabs.addTab(page, f["title"])
        # 尚未实现的功能占位页
        for title, note in (
            ("历史", "提交历史树（多色分支线 + 点 commit 看 diff）"),
            ("分支", "分支列表 + 切换守卫 + 上游关联"),
            ("对比", "两个分支的差异文件清单"),
        ):
            ph = QLabel(f"{note}\n（下一个里程碑）")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet("color:#888;")
            self.tabs.addTab(ph, title)
        split.addWidget(self.tabs)
        split.setSizes([180, 900])

        # ---- 提交条（第六章 3：固定底部、高度可拖动） ----
        commit_bar = QWidget()
        hc = QHBoxLayout(commit_bar)
        hc.setContentsMargins(8, 4, 8, 4)
        self.edit_msg = QLineEdit()
        self.edit_msg.setPlaceholderText("提交消息（一行写完）…")
        self.btn_commit = QPushButton("提交")
        self.btn_commit.setEnabled(False)   # 有勾选且有消息时激活
        self.btn_commit.clicked.connect(self._commit)
        self.edit_msg.textChanged.connect(self._update_commit_button)
        self.edit_msg.returnPressed.connect(self._commit)   # ≤3 秒流程：消息写完回车即提交
        hc.addWidget(self.edit_msg, 1)
        hc.addWidget(self.btn_commit)

        # ---- 命令与日志栏：可展开如终端（第六章 5 升级，2026-11-20 标定） ----
        log_pane = QWidget()
        log_pane.setObjectName("logpane")
        log_pane.setStyleSheet("QWidget#logpane{background:#1e1e1e;}")
        log_pane.setAttribute(Qt.WA_StyledBackground, True)
        lvp = QVBoxLayout(log_pane)
        lvp.setContentsMargins(6, 2, 6, 4)
        lvp.setSpacing(2)

        head_row = QHBoxLayout()
        self.btn_log_toggle = QPushButton("▸ 命令与日志")
        self.btn_log_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_log_toggle.setStyleSheet(
            "QPushButton{color:#9cdcfe;font-weight:bold;border:none;background:transparent;}")
        self.btn_log_toggle.clicked.connect(self._toggle_log)
        self.label_cmd_text = QLabel("")
        # 关键修复：Ignored 策略——长命令文本不再把窗口最小宽度撑爆
        self.label_cmd_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.label_cmd_text.setStyleSheet("color:#ccc;")
        head_row.addWidget(self.btn_log_toggle)
        head_row.addWidget(self.label_cmd_text, 1)
        lvp.addLayout(head_row)

        self.edit_log = QPlainTextEdit()
        self.edit_log.setReadOnly(True)
        self.edit_log.setStyleSheet(
            "QPlainTextEdit{background:#1a1a1a;color:#d4d4d4;"
            "font-family:Consolas,'Courier New',monospace;font-size:9pt;border:1px solid #333;}")
        self.edit_log.hide()
        lvp.addWidget(self.edit_log, 1)

        # 内嵌命令行：提示符 + 输入框（展开日志面板时可用）
        in_row = QHBoxLayout()
        prompt = QLabel("❯")
        prompt.setStyleSheet("color:#4ec9b0;font-weight:bold;font-family:Consolas,monospace;")
        self.edit_term = QLineEdit()
        self.edit_term.setPlaceholderText("输入命令，回车执行（ls/cat/grep 可用；clear 清屏；cd 切换目录）")
        self.edit_term.setStyleSheet(
            "QLineEdit{background:#1a1a1a;color:#d4d4d4;"
            "font-family:Consolas,monospace;border:1px solid #333;padding:2px 6px;}")
        self.edit_term.returnPressed.connect(self._run_typed_command)
        self.edit_term.hide()
        in_row.addWidget(prompt)
        in_row.addWidget(self.edit_term, 1)
        lvp.addLayout(in_row)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(split)
        vsplit.addWidget(commit_bar)
        vsplit.addWidget(log_pane)
        vsplit.setStretchFactor(0, 1)
        vsplit.setSizes([560, 60, 34])
        self._vsplit = vsplit   # 展开日志面板时同步调整分割配额
        root.addWidget(vsplit, 1)

        self.setCentralWidget(central)

    # ================================================ 仓库管理
    def _reload_repos(self) -> None:
        self.list_repo.blockSignals(True)
        self.list_repo.clear()
        for path in self.settings.get("repos", []):
            self.list_repo.addItem(path)
        self.list_repo.blockSignals(False)
        if self.list_repo.count():
            self.list_repo.setCurrentRow(0)   # 触发 _select_repo
        else:
            self.repo = None
            self._set_branch_text(None)
            page = self.pages.get("改动")
            if page:
                page.show_message("还没有打开仓库：点左下角「+ 添加仓库」")

    def _select_repo(self, path: str) -> None:
        if not path:
            return
        self.repo = GitRepo(path, self.log)
        self._term_cwd = path             # 切仓库时重置终端会话目录
        self.setWindowTitle(f"EasyGit —— {path}")
        self.refresh_status()

    def add_repo(self) -> None:
        """v1 #7 的一角：添加仓库（向导化、平台识别后续里程碑做）"""
        path = QFileDialog.getExistingDirectory(self, "选择一个 git 仓库文件夹")
        if not path:
            return
        repos = self.settings.setdefault("repos", [])
        if path not in repos:
            repos.append(path)
            settings_mod.save(self.settings)
        self._reload_repos()

    def open_terminal(self) -> None:
        """v1 #8：在当前仓库打开外部终端——GUI 覆盖不到的角落，命令行是逃生通道"""
        if not self.repo:
            return
        try:
            subprocess.Popen(["wt", "-d", self.repo.path])
        except FileNotFoundError:
            subprocess.Popen(
                ["powershell", "-NoExit", "-Command",
                 f"Set-Location -LiteralPath '{self.repo.path}'"])

    # ================================================ 功能页统一入口（统一执行管道）
    def run_git_job(self, fn, on_done=None) -> None:
        """后台执行一个 git 操作；完成后：报错大白话提示 → 自动刷新状态。
        fn(repo) -> CommandRecord；on_done(result) 总会先执行（result 可能是异常）。"""
        if not self.repo:
            return
        repo = self.repo

        def job():
            return fn(repo)

        def done(result):
            if on_done:
                on_done(result)              # 功能页自己的收尾（如解除 busy）总是执行
            if self.repo is not repo:          # 用户已切走仓库，丢弃过期结果
                return
            if isinstance(result, Exception):
                self.label_cmd_text.setStyleSheet("color:#f48771;")
                self.label_cmd_text.setText(f"操作失败：{result}")
                return
            if isinstance(result, CommandRecord) and not result.ok:
                first = result.output.splitlines()[0] if result.output else "执行失败"
                self.label_cmd_text.setStyleSheet("color:#f48771;")
                self.label_cmd_text.setText(
                    f"✗ {result.cmd} —— {translate_error(result.output) or first}")
                return
            self.refresh_status()

        run_async(job, done, parent=self, keep=self._workers)

    # ================================================ 状态刷新（异步，界面永不冻结）
    def refresh_status(self) -> None:
        if not self.repo:
            return
        repo = self.repo

        def job():
            return repo.status()

        def on_done(result):
            if self.repo is not repo:      # 用户已切走仓库，丢弃过期结果
                return
            if isinstance(result, Exception):
                self.label_cmd_text.setText(f"刷新失败：{result}")
                return
            self._render_status(result)

        run_async(job, on_done, parent=self, keep=self._workers)

    def _render_status(self, status: StatusInfo) -> None:
        # 分支 + 领先/落后（工具栏）
        self._set_branch_text(status.branch)
        # 提示条：仅异常出现（冲突中 / detached HEAD）
        conflicts = [f for f in status.files if f.group == "conflict"]
        if conflicts:
            self.label_banner.setText(
                f"⚠ 你处于合并冲突中：还剩 {len(conflicts)} 个文件没解决")
            self.banner.show()
        elif status.branch.detached:
            self.label_banner.setText(
                "⚠ 你不在任何分支上（detached HEAD），提交可能丢")
            self.banner.show()
        else:
            self.banner.hide()
        # 改动页 + 提交按钮 + 命令栏
        self._staged_count = sum(1 for f in status.files if f.group == "staged")
        self._update_commit_button()
        page = self.pages.get("改动")
        if page:
            page.refresh_from(status)
        self.label_cmd_text.setStyleSheet("color:#ccc;")
        self._sync_log_pane()

    # ================================================ 命令与日志面板（终端式）
    def _toggle_log(self) -> None:
        if self.edit_log.isHidden():
            self.edit_log.show()
            self.edit_term.show()
            self.edit_term.setFocus()
            self.btn_log_toggle.setText("▾ 命令与日志")
            self._vsplit.setSizes([500, 60, 220])   # 展开时给日志区让出高度
        else:
            self.edit_log.hide()
            self.edit_term.hide()
            self.btn_log_toggle.setText("▸ 命令与日志")
            self._vsplit.setSizes([560, 60, 34])    # 收起时还回去

    def _sync_log_pane(self) -> None:
        """把 CommandLog 里尚未显示的记录写入日志面板；摘要行只显示最近一条"""
        recs = list(self.log.records)
        for rec in recs[self._shown_log:]:
            mark = "OK  " if rec.ok else "FAIL"
            self.edit_log.appendPlainText(f"[{rec.time}] {mark} {rec.cmd}")
            if rec.output and (rec.show_output or not rec.ok):
                lines = rec.output.splitlines()[:200]   # 超长输出截断保护
                for line in lines:
                    self.edit_log.appendPlainText("      " + line)
        self._shown_log = len(recs)
        self.label_cmd_text.setText(recs[-1].cmd if recs else "")

    def _run_typed_command(self) -> None:
        """内嵌命令行：执行用户输入的命令（clear 清屏、cd 持久，贴近真终端手感）"""
        text = self.edit_term.text().strip()
        if not text or not self.repo:
            return
        cwd = self._term_cwd or self.repo.path

        # 屏幕类命令拦截：日志面板是文本框不是屏幕，clear 的转义码在这里没有意义
        if text in ("clear", "cls"):
            self.edit_term.clear()
            self.edit_log.clear()
            return
        if text == "cd" or text.startswith("cd "):
            self._cd_session(cwd, text[3:].strip() if len(text) > 2 else None)
            self.edit_term.clear()
            return

        self.edit_term.clear()
        self.edit_term.setEnabled(False)   # 执行期间锁定输入

        def job():
            return run_shell(cwd, text)

        def done(result):
            self.edit_term.setEnabled(True)
            self.edit_term.setFocus()
            if isinstance(result, Exception):
                self.log.add(CommandRecord(cmd=f"$ {text}", ok=False,
                                           output=str(result)))
            else:
                self.log.add(result)
            self._sync_log_pane()
            # 手敲的 git 命令也可能改了仓库状态 → 顺手刷新
            if text.split()[0] == "git":
                self.refresh_status()

        run_async(job, done, parent=self, keep=self._workers)

    def _cd_session(self, cwd: str, target: str | None) -> None:
        """内嵌终端的 cd：切换会话工作目录；不带参数 = 回仓库根目录"""
        if target is None:
            self._term_cwd = self.repo.path
            self.edit_log.appendPlainText(f"$ cd  →  {self._term_cwd}")
            return
        argv_path = target.replace("\\", "/")   # bash 只认正斜杠
        self.edit_term.setEnabled(False)

        def job():
            # pwd -W 是 Git Bash 扩展：输出 Windows 形式路径
            return run_shell(cwd, f"cd {argv_path} && pwd -W")

        def done(result):
            self.edit_term.setEnabled(True)
            self.edit_term.setFocus()
            if isinstance(result, Exception):
                self.log.add(CommandRecord(cmd=f"$ cd {target}", ok=False,
                                           output=str(result)))
                self._sync_log_pane()
                return
            if not result.ok:
                self.log.add(result)
                self._sync_log_pane()
                return
            new_cwd = result.output.strip().splitlines()[-1]
            self._term_cwd = new_cwd
            self.edit_log.appendPlainText(f"$ cd {target}  →  {new_cwd}")

        run_async(job, done, parent=self, keep=self._workers)

    # ================================================ 提交（≤3 秒流程）
    def _update_commit_button(self) -> None:
        has_msg = bool(self.edit_msg.text().strip())
        n = self._staged_count
        self.btn_commit.setEnabled(n > 0 and has_msg)
        self.btn_commit.setText(f"提交（{n} 个文件）" if n else "提交")

    def _commit(self) -> None:
        msg = self.edit_msg.text().strip()
        if not msg or not self.repo:
            return
        self.btn_commit.setEnabled(False)

        def on_done(rec):
            if isinstance(rec, CommandRecord) and rec.ok:
                self.edit_msg.clear()   # 提交成功后清空消息；状态由自动刷新更新

        self.run_git_job(lambda repo: repo.commit(msg), on_done)

    def _set_branch_text(self, branch) -> None:
        if branch is None or (not branch.name and not branch.detached):
            self.label_branch.setText("分支：—")
            self.label_branch.setStyleSheet("")
            self.label_ab.setText("")
            return
        if branch.detached:
            self.label_branch.setText("HEAD 游离（不在任何分支上）")
            self.label_branch.setStyleSheet("color:#c0392b;")
        else:
            self.label_branch.setText(f"分支：{branch.name}")
            self.label_branch.setStyleSheet("")
        if branch.upstream:
            self.label_ab.setText(f"↑{branch.ahead} ↓{branch.behind}")
        else:
            self.label_ab.setText("未关联远端")
