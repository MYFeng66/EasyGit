# -*- coding: utf-8 -*-
"""「改动」页 v0.5：两区（已修改 / 已加入）+ 目录树（Explorer 式，2026-11-21 用户标定）。

* 左侧上下两区：已修改（工作区） / 已加入（下次提交），勾选让文件在区间流动
* 文件按目录树组织、可展开折叠；列 = 名称 | 类型 | 状态
* 勾上 = 纳入下次提交（幕后 git add）；取消 = 拿出（幕后 git restore --staged）
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import register
from ...core.git_wrapper import GitFile, StatusInfo
from ...ui.diff_viewer import DiffViewer
from ...ui.stash_dialog import StashDialog

PATH_ROLE = Qt.UserRole + 1      # 完整相对路径（文件行）
OGROUP_ROLE = Qt.UserRole + 2     # git 侧的原始分组（untracked/conflict/…）
DIRPATHS_ROLE = Qt.UserRole + 3    # 目录行：它下面所有（非冲突）文件的路径列表

# 专业用词（用户标定：拒绝口水词）
WORKTREE_TEXT = {"M": "已修改", "D": "已删除", "R": "已重命名", "A": "新增", "?": "未跟踪"}


def _debug_log(msg: str) -> None:
    """改动页诊断日志（排查“文件列表消失”类问题用，可随时删除）"""
    try:
        log = Path.home() / ".easygit" / "debug.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _zone_term(f: GitFile, add_zone: bool) -> str:
    """状态列：已加入区看暂存码 x；已修改区看工作区码 y"""
    if not add_zone:
        if f.group == "untracked":
            return "未跟踪"
        if f.group == "conflict":
            return "冲突"
    return WORKTREE_TEXT.get(f.x if add_zone else f.y, "改动")


def _ext_of(path: str) -> str:
    suffix = Path(path).suffix
    return suffix if suffix else "（无扩展名）"


class ZonePanel(QWidget):
    """一个分区：标题行（数量 + 批量按钮）+ 目录树"""

    def __init__(self, title: str, color: str, batch_text: str,
                 on_batch, on_toggle, on_click):
        super().__init__()
        self.base_title = title
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 2)
        self.bar = bar          # 暴露给页面：可追加按钮（如「储藏…」）
        self.label_title = QLabel(title)
        font = QFont()
        font.setBold(True)
        self.label_title.setFont(font)
        self.label_title.setStyleSheet(f"color:{color};")
        self.btn_batch = QPushButton(batch_text)
        self.btn_batch.clicked.connect(on_batch)
        bar.addWidget(self.label_title)
        bar.addStretch(1)
        bar.addWidget(self.btn_batch)
        v.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "类型", "状态"])
        self.tree.setRootIsDecorated(True)
        # 行内边距——视觉上不再逼仄（用户标定 2026-11-21）
        self.tree.setStyleSheet("QTreeWidget::item{padding:3px 0;}")
        # 列宽规则（用户标定）：名称列弹性占满剩余空间；Qt 默认会拉伸【最后一列】，
        # 导致“状态”列吞掉所有宽度——必须关掉，改成名称列拉伸
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(on_toggle)
        self.tree.itemClicked.connect(on_click)
        v.addWidget(self.tree, 1)


class StatusPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._busy = False
        self._mod_files: list[GitFile] = []   # 已修改区文件（含未跟踪/冲突）
        self._add_files: list[GitFile] = []   # 已加入区文件

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)

        left = QSplitter(Qt.Vertical)
        self.zone_mod = ZonePanel(
            "已修改（工作区）", "#0d47a1", "全部加入",
            self._stage_all, self._on_toggle_mod, self._on_file_click)
        self.zone_add = ZonePanel(
            "已加入（下次提交）", "#1b5e20", "全部移出",
            self._unstage_all, self._on_toggle_add, self._on_file_click)
        left.addWidget(self.zone_mod)
        left.addWidget(self.zone_add)
        left.setSizes([320, 180])
        # 文件目录区（已修改）应比已加入区大（用户标定 2026-11-21）
        left.setStretchFactor(0, 2)
        left.setStretchFactor(1, 1)

        # 储藏入口：改动去哪了 → 在这里找回来（2026-11-21 用户需求）
        btn_stash = QPushButton("储藏…")
        btn_stash.clicked.connect(self._open_stash)
        self.zone_mod.bar.insertWidget(2, btn_stash)   # 批量按钮左侧

        split.addWidget(left)
        self.viewer = DiffViewer()
        split.addWidget(self.viewer)
        split.setSizes([680, 400])
        root.addWidget(split)

    # ================================================ 对外接口：主窗口刷新时调用
    def show_message(self, text: str) -> None:
        """还没打开仓库等场景"""
        _debug_log(f"列表被清空并显示提示：{text}")
        for panel in (self.zone_mod, self.zone_add):
            panel.tree.clear()
            panel.label_title.setText(panel.base_title)
        self.zone_mod.tree.addTopLevelItem(
            QTreeWidgetItem([text, "", ""]))
        self._mod_files = []
        self._add_files = []

    def refresh_from(self, status: StatusInfo) -> None:
        _debug_log(f"refresh_from：ok={status.ok} 文件数={len(status.files)}")
        self._busy = False
        self._mod_files = [f for f in status.files if f.group != "staged"]
        self._add_files = [f for f in status.files if f.group == "staged"]
        self._build_zone(self.zone_mod, self._mod_files, add_zone=False,
                         empty_text="工作区很干净，没有待处理的改动")
        self._build_zone(self.zone_add, self._add_files, add_zone=True,
                         empty_text="还没有加入任何文件")

    # ================================================ 目录树渲染
    def _build_zone(self, panel: ZonePanel, files: list[GitFile],
                    add_zone: bool, empty_text: str) -> None:
        tree = panel.tree
        tree.blockSignals(True)
        scroll = tree.verticalScrollBar().value()
        tree.clear()
        panel.label_title.setText(f"{panel.base_title}（{len(files)}）")

        if not files:
            tree.blockSignals(False)
            tree.addTopLevelItem(QTreeWidgetItem([empty_text, "", ""]))
            tree.verticalScrollBar().setValue(0)
            return

        # 递归建目录结构：嵌套 dict，叶子 = GitFile
        nested: dict = {}
        for f in files:
            parts = Path(f.path).parts
            d = nested
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = f

        def collect_files(d: dict) -> list:
            out = []
            for v in d.values():
                if isinstance(v, dict):
                    out.extend(collect_files(v))
                else:
                    out.append(v)
            return out

        def render(d: dict, parent) -> None:
            for name, val in d.items():
                if isinstance(val, dict):          # 子目录
                    dir_item = QTreeWidgetItem(parent, [name, "文件夹", ""])
                    # 目录也可整体勾选（2026-11-21 用户标定）：勾选 = 勾选全部下属文件
                    paths = [f.path for f in collect_files(val)
                             if f.group != "conflict"]
                    if paths:
                        dir_item.setData(0, DIRPATHS_ROLE, paths)
                        dir_item.setFlags(
                            Qt.ItemIsEnabled | Qt.ItemIsSelectable
                            | Qt.ItemIsUserCheckable)
                        dir_item.setCheckState(
                            0, Qt.Checked if add_zone else Qt.Unchecked)
                    else:
                        dir_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    render(val, dir_item)
                    dir_item.setExpanded(True)
                else:                              # 文件
                    f: GitFile = val
                    child = QTreeWidgetItem(
                        parent, [name, _ext_of(f.path), _zone_term(f, add_zone)])
                    child.setData(0, PATH_ROLE, f.path)
                    child.setData(0, OGROUP_ROLE, f.group)
                    if f.group == "conflict":
                        # 冲突文件不能直接勾选——留给冲突向导处理
                        for col in (0, 1, 2):
                            child.setForeground(col, QBrush(QColor("#c0392b")))
                        child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    else:
                        # 勾选即提交：勾选框状态 = git 暂存区的真实状态
                        child.setFlags(
                            Qt.ItemIsEnabled | Qt.ItemIsSelectable
                            | Qt.ItemIsUserCheckable)
                        child.setCheckState(
                            0, Qt.Checked if add_zone else Qt.Unchecked)

        render(nested, tree)
        tree.blockSignals(False)
        tree.verticalScrollBar().setValue(scroll)

    # ================================================ 勾选交互（勾选即提交）
    def _on_toggle_mod(self, item: QTreeWidgetItem, col: int) -> None:
        self._toggle(item, col, stage=True)

    def _on_toggle_add(self, item: QTreeWidgetItem, col: int) -> None:
        self._toggle(item, col, stage=False)

    def _toggle(self, item: QTreeWidgetItem, col: int, stage: bool) -> None:
        if col != 0:
            return
        path = item.data(0, PATH_ROLE)
        dir_paths = item.data(0, DIRPATHS_ROLE)
        if path is None and not dir_paths:
            return
        paths = [path] if path else list(dir_paths)
        if not paths:
            return
        if self._busy:
            # 后台操作进行中：把这次勾选视觉上退回去（真实状态稍后自动刷新）
            tree = item.treeWidget()
            tree.blockSignals(True)
            item.setCheckState(
                0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)
            tree.blockSignals(False)
            return
        self._busy = True

        def job(repo):
            # 幕后执行 git add / git restore --staged（目录 = 一次批量），命令栏照实显示
            return repo.stage(paths) if stage else repo.unstage(paths)

        def done(rec):
            self._busy = False    # 主窗口会自动刷新，文件在两区间流动

        self.ctx.run_git_job(job, done)

    def _stage_all(self) -> None:
        paths = [f.path for f in self._mod_files if f.group != "conflict"]
        if not paths or self._busy:
            return
        self._busy = True

        def done(rec):
            self._busy = False

        self.ctx.run_git_job(lambda repo: repo.stage(paths), done)

    def _unstage_all(self) -> None:
        paths = [f.path for f in self._add_files]
        if not paths or self._busy:
            return
        self._busy = True

        def done(rec):
            self._busy = False

        self.ctx.run_git_job(lambda repo: repo.unstage(paths), done)

    # ================================================ 单文件查看（diff / 源码 / 预览）
    # ================================================ 储藏管理
    def _open_stash(self) -> None:
        """储藏对话框：列出/取回/丢弃 stash（存得进，必须取得出）"""
        if not self.ctx.repo:
            return
        dlg = StashDialog(self.ctx, self)
        dlg.exec()
        self.ctx.refresh_status()

    def _on_file_click(self, item: QTreeWidgetItem, col: int) -> None:
        path = item.data(0, PATH_ROLE)
        group = item.data(0, OGROUP_ROLE)
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


def create_page(ctx) -> QWidget:
    return StatusPage(ctx)


register(create_page, title="改动", order=10)
