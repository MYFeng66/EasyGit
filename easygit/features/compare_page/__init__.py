# -*- coding: utf-8 -*-
"""「对比」页（v1 #9 轻量版，第三轮需求 C）：两个分支的差异文件清单。
差异按目录分组、增/删/改标注；点文件 → DiffViewer 显示两个分支间的 diff。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import register
from ...ui.diff_viewer import DiffViewer

BR_A_ROLE = Qt.UserRole + 30
BR_B_ROLE = Qt.UserRole + 31
FILE_ROLE = Qt.UserRole + 32

STATUS_TEXT = {"A": "新增 +", "D": "删除 −", "M": "修改 ~", "R": "改名 →"}


class ComparePage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._repo = None

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("对比："))
        self.combo_a = QComboBox()
        self.combo_b = QComboBox()
        for c in (self.combo_a, self.combo_b):
            c.setMinimumWidth(220)
        btn = QPushButton("对比")
        btn.setStyleSheet("font-weight:bold;")
        btn.clicked.connect(self._compare)
        bar.addWidget(self.combo_a)
        bar.addWidget(QLabel("vs"))
        bar.addWidget(self.combo_b)
        bar.addWidget(btn)
        bar.addStretch(1)
        v.addLayout(bar)

        self.note = QLabel("选两个分支 → 点「对比」看它们差在哪些文件")
        self.note.setStyleSheet("color:#888;")
        v.addWidget(self.note)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["路径", "状态"])
        # 关掉“最后一列拉伸”默认行为：路径列才该是弹性列
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemClicked.connect(self._show_diff)
        split.addWidget(self.tree)
        self.viewer = DiffViewer()
        split.addWidget(self.viewer)
        split.setSizes([460, 540])
        v.addWidget(split, 1)

    # ================================================ 对外接口
    def reload_from_ctx(self) -> None:
        if self.ctx.repo:
            self.reload(self.ctx.repo)

    def reload(self, repo) -> None:
        self._repo = repo

        def job():
            return repo.branches()

        def done(result):
            if self._repo is not repo:
                return          # 过期仓库的结果，丢弃
            if isinstance(result, Exception) or not result:
                return
            local, remote = result
            names = [e.name for e in local] + [e.name for e in remote]
            for combo in (self.combo_a, self.combo_b):
                prev = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                combo.setCurrentText(prev) if prev in names else None
                combo.blockSignals(False)

        self.ctx.run_job(job, done)

    # ================================================ 对比与展示
    def _compare(self) -> None:
        repo = self._repo
        a = self.combo_a.currentText()
        b = self.combo_b.currentText()
        if not (repo and a and b):
            return
        if a == b:
            self.note.setText("请选两个**不同**的分支。")
            return

        def job():
            return repo.compare_branches(a, b)

        def done(result):
            if isinstance(result, Exception):
                return
            self._build_tree(a, b, result or [])

        self.ctx.run_job(job, done)

    def _build_tree(self, a: str, b: str, files: list) -> None:
        self.tree.clear()
        self.viewer.clear_view()
        if not files:
            self.note.setText(f"「{a}」和「{b}」内容一致，没有差异文件。")
            return
        self.note.setText(
            f"「{a}」→「{b}」共 {len(files)} 个文件不同；点文件看 diff。")

        by_dir: dict[str, list] = {}
        for status, path in files:
            d = str(Path(path).parent)
            if d in (".", ""):
                d = "（根目录）"
            by_dir.setdefault(d, []).append((status, path))

        bold = QFont()
        bold.setBold(True)
        for d in sorted(by_dir):
            header = QTreeWidgetItem([f"{d}（{len(by_dir[d])}）"])
            header.setFont(0, bold)
            self.tree.addTopLevelItem(header)
            for status, path in by_dir[d]:
                child = QTreeWidgetItem(
                    [Path(path).name or path, STATUS_TEXT.get(status[:1], status)])
                child.setData(0, BR_A_ROLE, a)
                child.setData(0, BR_B_ROLE, b)
                child.setData(0, FILE_ROLE, path)
                header.addChild(child)
            header.setExpanded(True)

    def _show_diff(self, item: QTreeWidgetItem) -> None:
        a = item.data(0, BR_A_ROLE)
        b = item.data(0, BR_B_ROLE)
        path = item.data(0, FILE_ROLE)
        repo = self._repo
        if not (a and b and path and repo):
            return

        def job():
            return repo.branch_diff(a, b, path)

        def done(result):
            if isinstance(result, Exception):
                return
            self.viewer.show_diff(result or "")

        self.ctx.run_job(job, done)


def create_page(ctx) -> QWidget:
    return ComparePage(ctx)


register(create_page, title="对比", order=40)
