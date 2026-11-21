# -*- coding: utf-8 -*-
"""「分支」页（v1 #3 上游关联可视化 + #4 切分支守卫 + 分支管理）。
本地/远端分组 + 搜索；右键：切换（守卫）/ 建立关联 / 删除 / 检出远端。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QMenu, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import register
from ...core.git_wrapper import BranchEntry, CommandRecord

NAME_ROLE = Qt.UserRole + 20
REMOTE_ROLE = Qt.UserRole + 21


class BranchPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._repo = None
        self._local: list[BranchEntry] = []
        self._remote: list[BranchEntry] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        bar = QHBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索分支…（对付几十条远端分支）")
        self.edit_search.textChanged.connect(self._populate)
        btn_reload = QPushButton("刷新")
        btn_reload.clicked.connect(self.reload_from_ctx)
        bar.addWidget(self.edit_search, 1)
        bar.addWidget(btn_reload)
        v.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["分支", "跟踪的远端分支"])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(self._double)
        v.addWidget(self.tree, 1)

    # ================================================ 对外接口
    def reload_from_ctx(self) -> None:
        if self.ctx.repo:
            self.reload(self.ctx.repo)

    def reload(self, repo) -> None:
        self._repo = repo

        def job():
            return repo.branches()

        def done(result):
            if isinstance(result, Exception):
                return
            self._local, self._remote = result
            self._populate()

        self.ctx.run_job(job, done)

    # ================================================ 列表渲染
    def _populate(self) -> None:
        self.tree.clear()
        kw = self.edit_search.text().strip().lower()
        bold = QFont()
        bold.setBold(True)
        for title, entries, is_remote in (
            ("本地", self._local, False),
            ("远端", self._remote, True),
        ):
            shown = [e for e in entries if kw in e.name.lower()]
            if not shown:
                continue
            header = QTreeWidgetItem([f"{title}（{len(shown)}）"])
            header.setFont(0, bold)
            self.tree.addTopLevelItem(header)
            for e in shown:
                label = ("● " if e.is_head else "") + e.name
                item = QTreeWidgetItem([label, e.upstream or "—"])
                if e.is_head:
                    item.setForeground(0, QBrush(QColor("#1b5e20")))
                item.setData(0, NAME_ROLE, e.name)
                item.setData(0, REMOTE_ROLE, is_remote)
                header.addChild(item)
            header.setExpanded(True)

    def _double(self, item: QTreeWidgetItem, col: int) -> None:
        """双击本地分支 = 切换（守卫自动触发）"""
        name = item.data(0, NAME_ROLE)
        if name and not item.data(0, REMOTE_ROLE):
            self._switch(name)

    # ================================================ 右键菜单
    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item or not item.data(0, NAME_ROLE):
            return
        name = item.data(0, NAME_ROLE)
        remote = item.data(0, REMOTE_ROLE)
        menu = QMenu(self)

        if remote:
            act = menu.addAction(f"检出「{name}」为新本地分支")
            act.triggered.connect(lambda: self._switch_remote(name))
        else:
            entry = next((e for e in self._local if e.name == name), None)
            is_head = bool(entry and entry.is_head)
            act = menu.addAction(f"切换到「{name}」")
            act.setEnabled(not is_head)
            act.triggered.connect(lambda: self._switch(name))
            if entry and not entry.upstream and not is_head:
                act2 = menu.addAction(f"建立关联并推送（push -u origin {name}）")
                act2.triggered.connect(lambda: self._push_upstream(name))
            if not is_head:
                act3 = menu.addAction(f"删除「{name}」")
                act3.triggered.connect(lambda: self._delete(name))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ================================================ 分支操作（全部走统一管道）
    def _after(self, rec) -> None:
        """操作成功后刷新分支列表；仓库状态由 run_git_job 自动刷新"""
        if isinstance(rec, CommandRecord) and rec.ok:
            self.reload_from_ctx()

    def _switch(self, name: str) -> None:
        """切换分支 —— 有未提交改动时弹出「切分支守卫」（v1 #4，痛点 B）"""
        repo = self._repo
        if not repo:
            return
        st = getattr(self.ctx, "_last_status", None)
        dirty = bool(st and any(f.group in ("staged", "unstaged") for f in st.files))
        if not dirty:
            self.ctx.run_git_job(lambda r: r.switch_branch(name), self._after)
            return

        box = QMessageBox(self)
        box.setWindowTitle("切分支守卫")
        box.setText(
            f"你有未提交的改动，直接切到「{name}」可能出问题。\n"
            "（git 只允许改动与目标分支不冲突时才带过去）\n\n怎么办？")
        b_carry = box.addButton("带着改动走", QMessageBox.AcceptRole)
        b_stash = box.addButton("先 stash 暂存再切换（改动不丢，随时可取回）",
                                QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked not in (b_carry, b_stash):
            return

        if clicked is b_carry:
            def job(repo):
                return repo.switch_branch(name)
        else:
            def job(repo):
                rec = repo.stash_push(f"EasyGit：切换到 {name} 前自动暂存")
                if not rec.ok:
                    return rec
                return repo.switch_branch(name)

        self.ctx.run_git_job(job, self._after)

    def _switch_remote(self, remote_name: str) -> None:
        """检出远端分支为新本地分支（origin/feature → 本地 feature）"""
        local = remote_name.split("/", 1)[-1]
        self.ctx.run_git_job(
            lambda r: r.switch_create(local, remote_name), self._after)

    def _push_upstream(self, name: str) -> None:
        """建立上游关联并推送（E 类痛点：一键 push -u）"""
        self.ctx.run_git_job(
            lambda r: r.push_set_upstream(branch=name), self._after)

    def _delete(self, name: str) -> None:
        """删除本地分支（第八章二次确认清单；说明未合并提交不真丢）"""
        btn = QMessageBox.question(
            self, "删除分支",
            f"删除本地分支「{name}」？\n"
            "（它指向的未合并提交仍在 git 的 reflog 里，v2「时间机器」可找回）",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn != QMessageBox.Yes:
            return
        self.ctx.run_git_job(lambda r: r.delete_branch(name), self._after)


def create_page(ctx) -> QWidget:
    return BranchPage(ctx)


register(create_page, title="分支", order=30)
