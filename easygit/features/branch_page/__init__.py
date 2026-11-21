# -*- coding: utf-8 -*-
"""「分支」页（v1 #3 上游关联可视化 + #4 切分支守卫 + 分支管理）。
本地/远端分组 + 搜索；右键：切换（守卫）/ 建立关联 / 删除 / 检出远端。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLineEdit, QMenu, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import register
from ...core.git_wrapper import (
    BranchEntry, CommandRecord, files_blocked_by_switch,
)

NAME_ROLE = Qt.UserRole + 20
REMOTE_ROLE = Qt.UserRole + 21


class BranchPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._repo = None
        self._local: list[BranchEntry] = []
        self._remote: list[BranchEntry] = []
        self._busy = False          # 有分支操作在后台跑时，忽略新的单击切换

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
        # 关掉“最后一列拉伸”默认行为：分支名列才该是弹性列
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        # 单击即切（用户标定 2026-11-21）；右键菜单保留完整操作集
        self.tree.itemClicked.connect(self._on_row_clicked)
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
            if self._repo is not repo:
                return          # 过期仓库的结果，丢弃
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
            # 字典序排序（用户标定 2026-11-21）
            shown = sorted(
                (e for e in entries if kw in e.name.lower()),
                key=lambda e: e.name.lower())
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

    def _on_row_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        """单击即切：本地 → 切分支（守卫）；远程 → 本地有同名则切过去，无则检出新分支"""
        name = item.data(0, NAME_ROLE)
        remote = item.data(0, REMOTE_ROLE)
        if not name or self._busy:
            return
        if remote:
            self._smart_remote(name)
            return
        entry = next((e for e in self._local if e.name == name), None)
        if entry and entry.is_head:
            return          # 当前分支：点击无动作
        self._switch(name)

    def _smart_remote(self, remote_name: str) -> None:
        """智能远程切换：origin/xxx → 本地已有 xxx 则切过去，没有则检出新分支"""
        local = remote_name.split("/", 1)[-1]
        if any(e.name == local for e in self._local):
            self._switch(local)
        else:
            self._switch_remote(remote_name)

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
        self._busy = False
        if isinstance(rec, CommandRecord) and rec.ok:
            self.reload_from_ctx()
        else:
            self._busy = False    # 失败也解锁，让用户能重试

    def _switch(self, name: str) -> None:
        """切换分支 —— 有未提交改动时弹出「切分支守卫」（v1 #4，痛点 B）"""
        repo = self._repo
        if not repo or self._busy:
            return
        self._busy = True
        st = getattr(self.ctx, "_last_status", None)
        dirty = bool(st and any(f.group in ("staged", "unstaged") for f in st.files))
        if not dirty:
            # 干净工作区也可能被未跟踪文件挡住 → 同样接住「拒绝」并弹救援窗
            self._switch_run(name, lambda r: r.switch_branch(name))
            return

        box = QMessageBox(self)
        box.setWindowTitle("切分支守卫")
        box.setText(
            f"你有未提交的改动，直接切到「{name}」可能被 git 拒绝。\n请选择处理方式：")
        b_carry = box.addButton("带着改动走\n（两分支文件相同时才放行）",
                                QMessageBox.AcceptRole)
        b_stash = box.addButton("stash 暂存后切换\n（改动存进储藏，切回后放回）",
                                QMessageBox.ActionRole)
        b_commit = box.addButton("先提交（去改动页）\n（提交 = 存档，最稳）",
                                 QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked not in (b_carry, b_stash, b_commit):
            self._busy = False    # 取消：解锁
            return
        if clicked is b_commit:
            self._busy = False
            self.ctx.tabs.setCurrentIndex(0)   # 去改动页先提交，提交即存档
            return
        if clicked is b_carry:
            self._switch_run(name, lambda r: r.switch_branch(name))
        else:
            self._switch_run(name, self._stash_then_switch_job(name))

    def _stash_then_switch_job(self, name: str, blocked: list[str] | None = None):
        """stash 后切换。blocked = 救援时点名的挡路文件：
        其中带 S 标记（skip-worktree）的先解除——stash 对这类改动隐形，
        不解除就会「不储存也不切换」（2026-11-21 用户实战发现）。"""
        def job(repo):
            if blocked:
                tracked = repo.tracked_subset(blocked)
                if tracked:
                    rec = repo.unmark_local(tracked)
                    if not rec.ok:
                        return rec
            rec = repo.stash_push(f"EasyGit：切换到 {name} 前自动暂存")
            if not rec.ok:
                return rec
            return repo.switch_branch(name)
        return job

    def _switch_run(self, name: str, job_fn) -> None:
        """执行切换；若被「会覆盖本地改动」拒绝 → 弹救援窗，不再只沉在命令栏（用户标定 2026-11-21）"""
        def on_done(rec):
            if isinstance(rec, CommandRecord) and not rec.ok \
                    and "overwritten" in rec.output:
                self._overwritten_rescue(name, rec)
                return
            self._after(rec)

        self.ctx.run_git_job(job_fn, on_done)

    def _overwritten_rescue(self, name: str, rec: CommandRecord) -> None:
        """git 拒绝切换：列出冲突文件，让用户选 stash / 仅本地 / 取消（用户标定 2026-11-21）"""
        blocked = files_blocked_by_switch(rec.output)
        files_text = "\n".join(blocked[:8]) or "\n".join(rec.output.splitlines()[:8])
        box = QMessageBox(self)
        box.setWindowTitle("切换被拒绝")
        box.setText(
            f"这些文件的本地改动会挡住切换到「{name}」：\n{files_text}\n"
            "请选择处理方式：")
        b_local = box.addButton("保持本地配置，直接切换\n（内容原样保留，也不会上传）",
                                QMessageBox.AcceptRole)
        b_stash = box.addButton("stash 暂存后切换\n（改动存进储藏，切回后放回）",
                                QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_local:
            self.ctx.run_git_job(
                self._local_then_switch_job(name, blocked), self._after)
            return
        if clicked is b_stash:
            # 先解除 S 标记再储藏；若仍被拒 → 重新弹救援（用户可改选仅本地）
            self._switch_run(name, self._stash_then_switch_job(name, blocked))
            return
        self._busy = False    # 取消：解锁

    def _local_then_switch_job(self, name: str, paths: list[str]):
        """保持本地配置 → 切换：全形态五步舞。
        跟踪的挡路文件：解除标记 → 清障；未跟踪的：直接删（都已先备份）。
        切换后内容原样盖回（目录不存在则重建），目标分支仍跟踪的重新标记仅本地。
        无论切换成败，用户文件必须原样盖回，一个字节都不能丢。"""
        def job(repo):
            backups = {}
            root = Path(repo.path)

            def write_back_all():
                for f, data in backups.items():
                    try:
                        target = root / f
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                    except OSError:
                        pass

            tracked_now, untracked_now = [], []
            for f in paths:
                full = root / f
                if full.is_file():
                    backups[f] = full.read_bytes()
                if repo.tracked_subset([f]):
                    tracked_now.append(f)
                else:
                    untracked_now.append(f)

            if tracked_now:
                rec = repo.unmark_local(tracked_now)   # 解除标记：git 正常看见
                if not rec.ok:
                    write_back_all()
                    return rec
                rec = repo.restore_paths(tracked_now)  # 清障：回到当前分支版本
                if not rec.ok:
                    write_back_all()
                    return rec
            for f in untracked_now:
                try:
                    (root / f).unlink()               # 未跟踪挡路：删除（已备份）
                except OSError:
                    pass

            rec = repo.switch_branch(name)
            write_back_all()                          # 无论成败：内容原样盖回
            if not rec.ok:
                return rec
            # 只重新标记在目标分支上仍被跟踪的文件；目标没有的 → 保持未跟踪即可
            still_tracked = repo.tracked_subset(list(backups))
            if still_tracked:
                repo.mark_local(still_tracked)
            return rec
        return job

    def _switch_remote(self, remote_name: str) -> None:
        """检出远端分支为新本地分支（origin/feature → 本地 feature）"""
        self._busy = True
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
