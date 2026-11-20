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
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .. import features
from ..core import settings as settings_mod
from ..core.executor import CommandLog
from ..core.git_wrapper import GitRepo, StatusInfo
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
        btn_terminal = QPushButton("打开终端")
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
        self.btn_commit.setEnabled(False)   # 勾选即提交在下一里程碑接入
        self.btn_commit.setToolTip("勾选即提交将在下一里程碑接入")
        hc.addWidget(self.edit_msg, 1)
        hc.addWidget(self.btn_commit)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(split)
        vsplit.addWidget(commit_bar)
        vsplit.setStretchFactor(0, 1)
        vsplit.setSizes([600, 70])
        root.addWidget(vsplit, 1)

        # ---- 命令预览与日志栏（第六章 5） ----
        cmd_bar = QWidget()
        cmd_bar.setObjectName("cmdbar")
        cmd_bar.setStyleSheet("QWidget#cmdbar{background:#1e1e1e;}")
        cmd_bar.setAttribute(Qt.WA_StyledBackground, True)
        hcmd = QHBoxLayout(cmd_bar)
        hcmd.setContentsMargins(8, 3, 8, 3)
        head_cmd = QLabel("▾ 命令预览与日志")
        head_cmd.setStyleSheet("color:#9cdcfe;font-weight:bold;")
        self.label_cmd_text = QLabel("")
        self.label_cmd_text.setStyleSheet("color:#ccc;")
        hcmd.addWidget(head_cmd)
        hcmd.addWidget(self.label_cmd_text, 1)
        root.addWidget(cmd_bar)

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
        # 改动页 + 命令栏
        page = self.pages.get("改动")
        if page:
            page.refresh_from(status)
        self.label_cmd_text.setText(self.log.tail_text(3))

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
