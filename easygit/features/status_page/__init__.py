# -*- coding: utf-8 -*-
"""「改动」页：状态面板 v0.1（对应需求文档 v1 #1 的首个里程碑）。
展示四个基本分组 + 大白话标题；退库检测/仅本地等分组后续里程碑接入。"""

from __future__ import annotations

from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .. import register
from ...core.git_wrapper import StatusInfo

# 分组标题 = 一句大白话（设计原则 1/痛点 G）
GROUPS = [
    ("conflict",  "冲突中 —— 同一文件两边都改了，需要你处理", "#c0392b"),
    ("staged",    "已勾选、将提交 —— 点「提交」就会生效", "#1b5e20"),
    ("unstaged",  "改了、未勾选 —— 改了，还没勾进本次提交", "#0d47a1"),
    ("untracked", "未跟踪 —— 新文件，还没进过版本库", "#616161"),
]

STATE_TEXT = {"M": "修改", "A": "新增", "D": "删除", "R": "改名", "U": "冲突", "?": "新"}


class StatusPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#888;")
        self.hint.hide()
        v.addWidget(self.hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件", "状态"])
        v.addWidget(self.tree, 1)

    # ---- 对外接口：主窗口刷新时调用 ----
    def show_message(self, text: str) -> None:
        """空状态提示（如：还没打开仓库 / 工作区干净）"""
        self.tree.clear()
        self.hint.setText(text)
        self.hint.show()

    def refresh_from(self, status: StatusInfo) -> None:
        self.hint.hide()
        self.tree.clear()
        if not status.files:
            self.show_message("工作区很干净，没有待处理的改动")
            return

        by_group: dict[str, list] = {}
        for f in status.files:
            by_group.setdefault(f.group, []).append(f)

        bold = QFont()
        bold.setBold(True)
        for key, title, color in GROUPS:
            files = by_group.get(key, [])
            if not files:
                continue
            header = QTreeWidgetItem([f"{title}（{len(files)}）"])
            header.setFont(0, bold)
            header.setForeground(0, QBrush(QColor(color)))
            self.tree.addTopLevelItem(header)
            for f in files:
                state = STATE_TEXT.get(f.x if f.x != " " else f.y, "改动")
                child = QTreeWidgetItem([f.path, state])
                if key == "conflict":
                    child.setForeground(0, QBrush(QColor("#c0392b")))
                header.addChild(child)
            header.setExpanded(True)


def create_page(ctx) -> QWidget:
    return StatusPage()


register(create_page, title="改动", order=10)
