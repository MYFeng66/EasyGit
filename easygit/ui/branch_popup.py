# -*- coding: utf-8 -*-
"""IDEA 式分支切换弹窗（2026-11-21 用户标定）。

点击工具栏分支名弹出：搜索过滤 + 本地/远程两节字典序 + 限高滚动
（80+ 分支不占屏）+ 单击即切 + 右键完整操作。行为委托给分支页。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QLineEdit, QMenu, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

NAME_ROLE = Qt.UserRole + 1
REMOTE_ROLE = Qt.UserRole + 2
HEAD_ROLE = Qt.UserRole + 3


class BranchPopup(QWidget):
    def __init__(self, branch_page, parent=None):
        super().__init__(parent, Qt.Popup)   # 无边框 + 点击外部自动关闭
        self.branch_page = branch_page
        self.setFixedWidth(360)
        self.setMaximumHeight(460)          # 80+ 分支也只占这块：内部滚动
        self.setStyleSheet("BranchPopup{background:white;border:1px solid #bbb;}")

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入以过滤分支名…")
        self.edit_search.textChanged.connect(self._filter)
        v.addWidget(self.edit_search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._pick)
        v.addWidget(self.tree, 1)

    # ================================================ 数据渲染
    def refresh(self, local, remote) -> None:
        """local/remote 为 BranchEntry 列表；两节各自按字典序"""
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        for title, entries, is_remote in (
            ("本地分支", local, False),
            ("远程分支", remote, True),
        ):
            if not entries:
                continue
            header = QTreeWidgetItem([f"{title}（{len(entries)}）"])
            header.setFont(0, bold)
            header.setForeground(0, QBrush(QColor("#666")))
            self.tree.addTopLevelItem(header)
            for e in sorted(entries, key=lambda x: x.name.lower()):
                label = ("● " if e.is_head else "　") + e.name
                item = QTreeWidgetItem([label])
                item.setData(0, NAME_ROLE, e.name)
                item.setData(0, REMOTE_ROLE, is_remote)
                item.setData(0, HEAD_ROLE, bool(e.is_head))
                if e.is_head:
                    item.setForeground(0, QBrush(QColor("#1b5e20")))
                header.addChild(item)
            header.setExpanded(True)

    def _filter(self) -> None:
        kw = self.edit_search.text().strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            visible = 0
            for j in range(top.childCount()):
                child = top.child(j)
                show = kw in (child.data(0, NAME_ROLE) or "").lower()
                child.setHidden(not show)
                if show:
                    visible += 1
            top.setHidden(visible == 0)

    # ================================================ 交互（委托分支页，守卫同源）
    def _pick(self, item: QTreeWidgetItem, col: int) -> None:
        name = item.data(0, NAME_ROLE)
        if not name:
            return
        self.close()      # 先关弹窗；若切分支守卫需要弹窗，在其后出现
        page = self.branch_page
        if item.data(0, REMOTE_ROLE):
            page._smart_remote(name)
        elif not item.data(0, HEAD_ROLE):
            page._switch(name)

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item or not item.data(0, NAME_ROLE):
            return
        name = item.data(0, NAME_ROLE)
        remote = bool(item.data(0, REMOTE_ROLE))
        page = self.branch_page
        menu = QMenu(self)
        if remote:
            act = menu.addAction(f"检出「{name}」为新本地分支")
            act.triggered.connect(lambda: (self.close(), page._smart_remote(name)))
        else:
            act = menu.addAction(f"切换到「{name}」")
            act.setEnabled(not item.data(0, HEAD_ROLE))
            act.triggered.connect(lambda: (self.close(), page._switch(name)))
            entry = next((e for e in page._local if e.name == name), None)
            if entry and not entry.upstream and not entry.is_head:
                act2 = menu.addAction(f"建立关联并推送（push -u origin {name}）")
                act2.triggered.connect(
                    lambda: (self.close(), page._push_upstream(name)))
            if not (entry and entry.is_head):
                act3 = menu.addAction(f"删除「{name}」")
                act3.triggered.connect(lambda: (self.close(), page._delete(name)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
