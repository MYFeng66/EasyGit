# -*- coding: utf-8 -*-
"""「改动」页 v0.4：单列表 + 双状态列 + 右侧 diff/源码/预览查看器。
勾上 = 纳入下次提交（幕后 git add）；取消 = 拿出（幕后 git restore --staged）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import register
from ...core.git_wrapper import StatusInfo
from ...ui.diff_viewer import DiffViewer

PATH_ROLE = Qt.UserRole + 1
GROUP_ROLE = Qt.UserRole + 2

# 专业用词（用户标定：拒绝口水词）：工作区列 = 文件当前状态
WORKTREE_TEXT = {"M": "已修改", "D": "已删除", "R": "已重命名", "A": "新增", "?": "未跟踪"}


class StatusPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx                    # 主窗口：提供 run_git_job（统一执行管道）
        self._busy = False                # 后台操作进行中时，忽略新勾选
        self._status = None               # 最近一次状态（供“全部勾选/取消”用）

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        # 顶部操作行
        top = QHBoxLayout()
        top.addWidget(QLabel("文件改动"))
        top.addStretch(1)
        btn_all = QPushButton("全部勾选")
        btn_all.clicked.connect(self._stage_all)
        btn_none = QPushButton("全部取消")
        btn_none.clicked.connect(self._unstage_all)
        top.addWidget(btn_all)
        top.addWidget(btn_none)
        v.addLayout(top)

        note = QLabel("勾选 = 纳入下次提交；「工作区」显示文件当前状态，「下次提交」显示它是否在本次提交中")
        note.setStyleSheet("color:#888;")
        v.addWidget(note)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#888;")
        self.hint.hide()
        v.addWidget(self.hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件", "工作区", "下次提交"])
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._show_file_diff)
        v.addWidget(self.tree, 1)

        # 右侧：diff / 源码 / 预览 公共查看器（与文件列表可拖动分割）
        split.addWidget(left)
        self.viewer = DiffViewer()
        split.addWidget(self.viewer)
        split.setSizes([460, 540])
        root.addWidget(split)

    # ---- 对外接口：主窗口刷新时调用 ----
    def show_message(self, text: str) -> None:
        """空状态提示（如：还没打开仓库 / 工作区干净）"""
        self.tree.clear()
        self.hint.setText(text)
        self.hint.show()

    def refresh_from(self, status: StatusInfo) -> None:
        self._busy = False               # 每次刷新解除 busy（可自愈任何卡住的状态）
        self._status = status
        vbar = self.tree.verticalScrollBar()   # 记住滚动位置，重绘后还原
        scroll = vbar.value()

        self.hint.hide()
        self.tree.blockSignals(True)
        self.tree.clear()
        if not status.files:
            self.tree.blockSignals(False)
            self.show_message("工作区很干净，没有待处理的改动")
            return

        # 单列表：每个文件固定一行，勾选只改「下次提交」列，不跳动分组
        for f in status.files:
            group = f.group
            if group == "conflict":
                wt, nxt = "冲突", "待处理"
            elif group == "untracked":
                wt, nxt = "未跟踪", "—"
            elif group == "staged":
                wt = WORKTREE_TEXT.get(f.y, "—") if f.y != " " else "—"
                nxt = "已加入"
            else:  # unstaged
                wt = WORKTREE_TEXT.get(f.y, "改动")
                nxt = "—"
            child = QTreeWidgetItem([f.path, wt, nxt])
            child.setData(0, PATH_ROLE, f.path)
            child.setData(0, GROUP_ROLE, group)
            if group == "conflict":
                # 冲突文件不能直接勾选——留给冲突向导处理
                for col in (0, 1, 2):
                    child.setForeground(col, QBrush(QColor("#c0392b")))
            else:
                # 勾选即提交：勾选框状态 = git 暂存区的真实状态
                child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if group == "staged" else Qt.Unchecked)
            self.tree.addTopLevelItem(child)
        self.tree.blockSignals(False)
        vbar.setValue(scroll)


    # ================================================ 单文件查看（diff / 源码 / 预览）
    def _show_file_diff(self, item: QTreeWidgetItem, col: int) -> None:
        path = item.data(0, PATH_ROLE)
        group = item.data(0, GROUP_ROLE)
        if not path or not self.ctx.repo:
            return
        repo = self.ctx.repo

        # 源码：直接读工作区文件（删除/读不到 → None，按钮自动禁用）
        source = None
        try:
            fp = Path(repo.path) / path
            if fp.is_file() and fp.stat().st_size < 500_000:
                source = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = None

        if group == "untracked":
            # 未跟踪新文件：没有“与 HEAD 的差异”概念，直接看源码/预览
            self.viewer.set_content(path=path, diff_text="", source_text=source)
            return

        def job():
            return repo.file_diff_head(path)

        def done(result):
            if isinstance(result, Exception):
                return
            self.viewer.set_content(path=path, diff_text=result or "",
                                    source_text=source)

        self.ctx.run_job(job, done)

    # ================================================ 勾选交互（勾选即提交）
    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0 or item.data(0, PATH_ROLE) is None:
            return
        if self._busy:
            # 后台操作进行中：把这次勾选视觉上退回去（git 真实状态稍后自动刷新）
            self.tree.blockSignals(True)
            item.setCheckState(
                0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)
            self.tree.blockSignals(False)
            return
        want_stage = item.checkState(0) == Qt.Checked
        path = item.data(0, PATH_ROLE)
        self._busy = True

        def job(repo):
            # 幕后执行 git add / git restore --staged，命令栏照实显示
            return repo.stage([path]) if want_stage else repo.unstage([path])

        def done(rec):
            self._busy = False

        self.ctx.run_git_job(job, done)

    def _stage_all(self) -> None:
        if self._busy or not self._status:
            return
        paths = [f.path for f in self._status.files
                 if f.group in ("unstaged", "untracked")]
        if not paths:
            return
        self._busy = True

        def done(rec):
            self._busy = False

        self.ctx.run_git_job(lambda repo: repo.stage(paths), done)

    def _unstage_all(self) -> None:
        if self._busy or not self._status:
            return
        paths = [f.path for f in self._status.files if f.group == "staged"]
        if not paths:
            return
        self._busy = True

        def done(rec):
            self._busy = False

        self.ctx.run_git_job(lambda repo: repo.unstage(paths), done)


def create_page(ctx) -> QWidget:
    return StatusPage(ctx)


register(create_page, title="改动", order=10)
