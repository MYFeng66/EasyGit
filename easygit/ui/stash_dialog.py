# -*- coding: utf-8 -*-
"""储藏（stash）管理对话框：切分支前自动暂存的改动，在这里取回/丢弃。
对应守卫与救援弹窗的 stash 选项——存得进去，就必须取得出来。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout,
)

from ..core.git_wrapper import CommandRecord

REF_ROLE = Qt.UserRole + 1


class StashDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("储藏（stash）")
        self.resize(600, 340)

        v = QVBoxLayout(self)
        self.label_hint = QLabel(
            "这里存着切换分支前被自动暂存的改动。\n"
            "选中一条 →「恢复取回」放回当前工作区（建议先切回原来的分支再取）。")
        self.label_hint.setWordWrap(True)
        v.addWidget(self.label_hint)

        self.list = QListWidget()
        v.addWidget(self.list, 1)

        row = QHBoxLayout()
        btn_pop = QPushButton("恢复取回")
        btn_pop.setStyleSheet("font-weight:bold;")
        btn_drop = QPushButton("丢弃")
        btn_close = QPushButton("关闭")
        row.addWidget(btn_pop)
        row.addWidget(btn_drop)
        row.addStretch(1)
        row.addWidget(btn_close)
        v.addLayout(row)

        btn_pop.clicked.connect(self._pop)
        btn_drop.clicked.connect(self._drop)
        btn_close.clicked.connect(self.reject)
        self._reload()

    # ================================================ 内部
    def _current_ref(self) -> str:
        item = self.list.currentItem()
        return item.data(REF_ROLE) if item else ""

    def _reload(self) -> None:
        self.list.clear()
        if not self.ctx.repo:
            return
        entries = self.ctx.repo.stash_list()
        if not entries:
            self.list.addItem("（储藏是空的——你的改动都不在这里）")
            return
        for e in entries:
            item = QListWidgetItem(f"{e.ref}　　{e.message}")
            item.setData(REF_ROLE, e.ref)
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def _pop(self) -> None:
        ref = self._current_ref()
        if not ref or not self.ctx.repo:
            return

        def job(repo):
            # run_git_job 的约定：fn(repo) —— 会把仓库当参数传入
            return repo.stash_pop(ref)

        def done(rec):
            if isinstance(rec, CommandRecord) and not rec.ok:
                QMessageBox.warning(
                    self, "取回有冲突",
                    "取回时发生了冲突，git 已保留这条储藏。\n"
                    "建议：切回当初暂存时的分支，再来取回。")
            self._reload()

        self.ctx.run_git_job(job, done)

    def _drop(self) -> None:
        ref = self._current_ref()
        if not ref or not self.ctx.repo:
            return
        btn = QMessageBox.question(
            self, "丢弃储藏",
            f"丢弃 {ref}？\n里面的改动将无法找回。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn != QMessageBox.Yes:
            return

        def job(repo):
            # run_git_job 的约定：fn(repo)
            return repo.stash_drop(ref)

        def done(rec):
            self._reload()

        self.ctx.run_git_job(job, done)
