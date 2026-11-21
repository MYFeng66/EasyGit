# -*- coding: utf-8 -*-
"""冲突解决向导（v1 #6，痛点 A）：编辑 → 标记已解决 → 一键完成合并提交。
闭环引导：解决冲突的完整链路是「编辑干净 → git add → git commit」，
本向导把后两步按钮化，用户只需要做真正需要人脑的部分——改文件。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout,
)


class ConflictDialog(QDialog):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("冲突解决向导")
        self.resize(560, 400)

        v = QVBoxLayout(self)
        self.label_info = QLabel("")
        self.label_info.setWordWrap(True)
        v.addWidget(self.label_info)

        self.list = QListWidget()
        v.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.btn_open = QPushButton("打开文件")
        self.btn_resolved = QPushButton("标记已解决")
        self.btn_finish = QPushButton("完成合并提交")
        self.btn_finish.setStyleSheet("font-weight:bold;padding:4px 12px;")
        btn_close = QPushButton("关闭")
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_resolved)
        row.addStretch(1)
        row.addWidget(btn_close)
        row.addWidget(self.btn_finish)
        v.addLayout(row)

        self.btn_open.clicked.connect(self._open_file)
        self.btn_resolved.clicked.connect(self._mark_resolved)
        self.btn_finish.clicked.connect(self._finish)
        btn_close.clicked.connect(self.reject)
        self._refresh()

    # ================================================ 内部流程
    def _current(self) -> str:
        item = self.list.currentItem()
        return item.text() if item else ""

    def _open_file(self) -> None:
        """用系统默认程序打开冲突文件（在编辑器里把 <<<<<<< 处理干净）"""
        path = self._current()
        if path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self.repo.path) / path)))

    def _mark_resolved(self) -> None:
        """标记已解决（幕后 git add）"""
        path = self._current()
        if path:
            self.repo.stage([path])
            self._refresh()

    def _finish(self) -> None:
        """一键完成合并提交（幕后 git commit --no-edit）"""
        rec = self.repo.conclude_merge()
        if rec.ok:
            self.accept()
        else:
            first = rec.output.splitlines()[0] if rec.output else "执行失败"
            self.label_info.setText(f"完成合并失败：{first}")

    def _refresh(self) -> None:
        files = self.repo.unmerged_files()
        self.list.clear()
        self.list.addItems(files)
        n = len(files)
        if n:
            self.label_info.setText(
                f"还剩 {n} 个文件没解决。\n"
                "步骤：选中文件 →「打开文件」把冲突标记（<<<<<<< ======= >>>>>>>）"
                "处理干净并保存 → 回来点「标记已解决」。全部解决后点「完成合并提交」。")
        else:
            self.label_info.setText("所有冲突文件都已标记解决 → 点「完成合并提交」收尾。")
        self.btn_finish.setEnabled(n == 0 and self.repo.merge_in_progress())
        self.btn_open.setEnabled(n > 0)
        self.btn_resolved.setEnabled(n > 0)
