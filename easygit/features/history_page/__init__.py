# -*- coding: utf-8 -*-
"""「历史」页：提交历史树 v1（多色泳道 + 点 commit 看文件清单与 diff）。
对应需求文档 v1 #5 与第七章 3 的形态。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QStyle,
    QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .. import register
from ...core.git_wrapper import Commit
from ...core.history_layout import assign_lanes
from ...ui.diff_viewer import DiffViewer

COMMIT_ROLE = Qt.UserRole + 10
FILE_HASH_ROLE = Qt.UserRole + 11
FILE_PATH_ROLE = Qt.UserRole + 12

LANE_COLORS = ["#3f51b5", "#e91e63", "#009688", "#ff9800", "#9c27b0", "#7cb342"]
LANE_SPACING = 14
GRAPH_MARGIN = 8
ROW_HEIGHT = 24
TEXT_X = 130           # 图形区宽度之后开始画文字


class GraphDelegate(QStyledItemDelegate):
    """历史列表的泳道绘制：竖线 + 合流/分叉横线 + 提交圆点 + 文字"""

    def sizeHint(self, option, index):
        return QSize(600, ROW_HEIGHT)

    def paint(self, painter, option, index):
        c = index.data(COMMIT_ROLE)
        if c is None:
            super().paint(painter, option, index)
            return
        rect = option.rect
        yc = rect.top() + rect.height() // 2

        # 背景（选中/悬停/斑马纹）
        if option.state & QStyle.State_Selected:
            bg = QColor("#cfe8ff")
        elif option.state & QStyle.State_MouseOver:
            bg = QColor("#f0f7ff")
        else:
            bg = QColor("#fafafa") if index.row() % 2 else QColor("white")
        painter.fillRect(rect, bg)

        def gx(lane: int) -> int:
            return GRAPH_MARGIN + lane * LANE_SPACING + LANE_SPACING // 2

        def lane_col(l: int) -> QColor:
            return QColor(LANE_COLORS[l % len(LANE_COLORS)])

        pen = QPen()
        pen.setWidth(2)

        # 竖线：上半（从上一行来）、下半（去往下一行）
        for l in c.lanes_above:
            pen.setColor(lane_col(l))
            painter.setPen(pen)
            painter.drawLine(gx(l), rect.top(), gx(l), yc)
        for l in c.lanes_below:
            pen.setColor(lane_col(l))
            painter.setPen(pen)
            painter.drawLine(gx(l), yc, gx(l), rect.bottom())

        # 合流横线（别的泳道并入本提交）
        for a, b in c.merge_edges:
            pen.setColor(lane_col(a))
            painter.setPen(pen)
            painter.drawLine(gx(a), yc, gx(b), yc)
        # 分叉横线（本提交开新泳道）
        for a, b in c.fork_edges:
            pen.setColor(lane_col(b))
            painter.setPen(pen)
            painter.drawLine(gx(a), yc, gx(b), yc)

        # 提交圆点（白边 + 泳道色）
        pen.setColor(QColor("white"))
        painter.setPen(pen)
        painter.setBrush(lane_col(c.lane))
        painter.drawEllipse(gx(c.lane) - 5, yc - 5, 10, 10)

        # 文字：短哈希 → 分支指针 → 消息 →（右缘）作者·时间
        painter.setFont(QFont("Consolas", 9))
        painter.setPen(QColor("#999"))
        painter.drawText(TEXT_X, rect.top(), 50, rect.height(),
                        Qt.AlignVCenter, c.short)

        rx = TEXT_X + 55
        if c.refs:
            bold = QFont()
            bold.setBold(True)
            painter.setFont(bold)
            for ref in c.refs:
                text = f"[{ref}]"
                w = painter.fontMetrics().horizontalAdvance(text) + 4
                painter.setPen(QColor("#c0392b") if "HEAD" in ref else QColor("#1565c0"))
                painter.drawText(rx, rect.top(), w, rect.height(),
                                Qt.AlignVCenter, text)
                rx += w

        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor("#333"))
        painter.drawText(rx, rect.top(), rect.right() - rx - 170, rect.height(),
                        Qt.AlignVCenter, c.subject)
        painter.setPen(QColor("#888"))
        painter.drawText(rect.right() - 166, rect.top(), 160, rect.height(),
                         Qt.AlignVCenter | Qt.AlignRight,
                         f"{c.author} · {c.date_rel}")


class HistoryPage(QWidget):
    PAGE = 50          # 每页提交数（滚动到底自动翻页）

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._repo = None
        self._commits: list[Commit] = []
        self._skip = 0
        self._busy = False
        self._pending_reload = False   # busy 期间收到的新仓库加载请求，done 里补跑

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        self.label_count = QLabel("切换仓库后这里显示提交历史")
        self.label_count.setStyleSheet("color:#666;")
        # 搜索过滤（总改造一期：大仓库找提交的刚需）
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索提交（消息 / 作者 / 哈希）")
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.setFixedWidth(260)
        self.edit_search.textChanged.connect(self._apply_filter)
        btn_more = QPushButton("加载更多")
        btn_more.clicked.connect(lambda: self._load(more=True))
        btn_reload = QPushButton("刷新")
        btn_reload.clicked.connect(self.reload_from_ctx)
        bar.addWidget(self.label_count)
        bar.addStretch(1)
        bar.addWidget(self.edit_search)
        bar.addWidget(btn_more)
        bar.addWidget(btn_reload)
        v.addLayout(bar)

        split = QSplitter(Qt.Horizontal)

        self.list = QListWidget()
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(GraphDelegate(self.list))
        self.list.itemClicked.connect(self._show_commit)
        self.list.verticalScrollBar().valueChanged.connect(self._on_scroll)
        # 右键：版本恢复（detached 查看 / 从版本建分支）
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._commit_menu)
        split.addWidget(self.list)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)
        rv.setSpacing(4)
        self.label_meta = QLabel("点左侧任意提交，这里显示它的信息与改动文件")
        self.label_meta.setWordWrap(True)
        self.label_meta.setStyleSheet("color:#555;")
        rv.addWidget(self.label_meta)
        self.list_files = QListWidget()
        self.list_files.itemClicked.connect(self._show_file_diff)
        # 右键：把单个文件恢复成该版本的样子
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_files.customContextMenuRequested.connect(self._file_menu)
        rv.addWidget(self.list_files, 1)
        self.viewer_diff = DiffViewer()
        rv.addWidget(self.viewer_diff, 1)
        split.addWidget(right)
        split.setSizes([660, 420])
        v.addWidget(split, 1)

    # ================================================ 搜索过滤（总改造一期）
    def _apply_filter(self, text: str) -> None:
        """客户端过滤已加载的提交：关键词命中消息/作者/哈希（不区分大小写）"""
        kw = text.strip().lower()
        hit_n = 0
        for i in range(self.list.count()):
            c = self.list.item(i).data(COMMIT_ROLE)
            hit = not kw or (c and (kw in c.subject.lower()
                                    or kw in c.author.lower()
                                    or kw in c.hash.lower()
                                    or kw in c.short.lower()))
            self.list.setRowHidden(i, not hit)
            if hit:
                hit_n += 1
        if kw:
            self.label_count.setText(
                f"匹配 {hit_n} / 已加载 {self.list.count()} 条（可点「加载更多」扩大范围）")
        else:
            self.label_count.setText(
                f"已加载 {self.list.count()} 条提交")

    # ================================================ 对外接口
    def reload_from_ctx(self) -> None:
        if self.ctx.repo:
            self.reload(self.ctx.repo)

    def reload(self, repo) -> None:
        """主窗口在选仓库 / 提交成功后调用"""
        self._repo = repo
        self._skip = 0
        self._commits = []
        self.list.clear()
        self.list_files.clear()
        self.viewer_diff.clear_view()
        self.label_meta.setText("点左侧任意提交，这里显示它的信息与改动文件")
        self.label_count.setText("正在读取提交历史…")
        self._load()

    # ================================================ 加载与翻页
    def _on_scroll(self, value: int) -> None:
        bar = self.list.verticalScrollBar()
        if value >= bar.maximum() - 2 and self.list.count() and not self._busy:
            self._load(more=True)

    def _load(self, more: bool = False) -> None:
        if not self._repo:
            return
        if self._busy:
            # 正在加载旧仓库 → 挂起本次，done 里补跑（否则新仓库数据永远丢失）
            self._pending_reload = True
            return
        self._busy = True
        repo = self._repo
        skip = self._skip

        def job():
            return repo.log(skip=skip, limit=self.PAGE)

        def done(result):
            self._busy = False
            if self._pending_reload:
                # 期间收到过新的加载请求（换仓库）→ 本结果作废，补跑新仓库
                self._pending_reload = False
                self.reload(self._repo)
                return
            if self._repo is not repo:
                return          # 纯过期结果（无新请求）：丢弃
            if isinstance(result, Exception):
                self.label_count.setText("读取提交历史失败")
                return
            if not result:
                self.label_count.setText(
                    "暂无更多提交" if more else "这个仓库还没有提交记录")
                return
            self._commits.extend(result)
            assign_lanes(self._commits)
            # 泳道依赖前后行 → 每次全量重绘
            self.list.clear()
            for c in self._commits:
                item = QListWidgetItem()
                item.setData(COMMIT_ROLE, c)
                self.list.addItem(item)
            self._skip = len(self._commits)
            self.label_count.setText(f"已加载 {len(self._commits)} 条提交")
            # 重建列表后重新套用当前搜索词
            self._apply_filter(self.edit_search.text())

        self.ctx.run_job(job, done)

    # ================================================ 详情与 diff
    def _show_commit(self, item: QListWidgetItem) -> None:
        c = item.data(COMMIT_ROLE)
        repo = self._repo
        if not (c and repo):
            return
        refs = "  ".join(f"[{r}]" for r in c.refs)
        self.label_meta.setText(
            f"{refs}\n{c.subject}\n{c.author} · {c.date_rel}\n完整哈希：{c.hash}")
        self.list_files.clear()
        self.viewer_diff.clear_view()

        def job():
            return repo.commit_files(c.hash)

        def done(result):
            if isinstance(result, Exception) or result is None:
                return
            for status, path in result:
                fi = QListWidgetItem(f"{status:<8} {path}")
                fi.setData(FILE_HASH_ROLE, c.hash)
                fi.setData(FILE_PATH_ROLE, path)
                self.list_files.addItem(fi)
            if not result:
                self.list_files.addItem("（空提交或合并提交，未直接改文件）")

        self.ctx.run_job(job, done)

    # ================================================ 版本恢复（右键菜单，2026-11-21）
    def _commit_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if not item:
            return
        c = item.data(COMMIT_ROLE)
        if not c:
            return
        menu = QMenu(self)
        act_view = menu.addAction("回到这个版本看看\n（HEAD 指过去，不改分支，随时一键回来）")
        act_view.triggered.connect(lambda: self._checkout_version(c))
        act_branch = menu.addAction("从这个版本创建新分支…")
        act_branch.triggered.connect(lambda: self._branch_at_version(c))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _checkout_version(self, c) -> None:
        """detached 查看旧版本：记住原分支，横幅提供一键回家。
        2026-11-21 实战加固：脏树时先警告（改动会跟着你走；在旧版本里提交后回家会丢）"""
        st = getattr(self.ctx, "_last_status", None)
        dirty = st and any(f.group in ("staged", "unstaged") for f in st.files)
        if dirty:
            btn = QMessageBox.question(
                self, "有未提交改动",
                "工作区有未提交改动。看旧版本时这些改动会跟着你走；\n"
                "若在旧版本里把它们提交，回家时提交会被搁下丢失。\n\n"
                "建议先提交或储藏，再去看旧版本。\n仍要看旧版本吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if btn != QMessageBox.Yes:
                return
        st2 = getattr(self.ctx, "_last_status", None)
        if st2 and st2.branch and not st2.branch.detached and st2.branch.name:
            self.ctx._detach_return_branch = st2.branch.name

        def job(repo):
            return repo.checkout_detached(c.hash)

        self.ctx.run_git_job(job, None)   # 自动刷新 → 横幅出现

    def _branch_at_version(self, c) -> None:
        name, ok = QInputDialog.getText(
            self, "从版本建分支",
            f"从「{c.subject[:30]}」({c.short}) 创建新分支：",
            text=f"version-{c.short}")
        if not ok or not name.strip():
            return
        new_name = name.strip()

        def job(repo):
            return repo.switch_create_at(c.hash, new_name)

        self.ctx.run_git_job(job, None)

    def _file_menu(self, pos) -> None:
        item = self.list_files.itemAt(pos)
        if not item:
            return
        c_hash = item.data(FILE_HASH_ROLE)
        path = item.data(FILE_PATH_ROLE)
        if not (c_hash and path):
            return
        menu = QMenu(self)
        act = menu.addAction("把这个文件恢复成该版本的样子\n（覆盖工作区的未提交改动）")
        act.triggered.connect(lambda: self._restore_file(c_hash, path))
        menu.exec(self.list_files.viewport().mapToGlobal(pos))

    def _restore_file(self, c_hash: str, path: str) -> None:
        btn = QMessageBox.question(
            self, "恢复文件",
            f"把「{path}」恢复成所选版本的样子？\n"
            "工作区里这个文件的未提交改动将被覆盖。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn != QMessageBox.Yes:
            return

        def job(repo):
            return repo.restore_file_from(c_hash, path)

        self.ctx.run_git_job(job, None)

    def _show_file_diff(self, item: QListWidgetItem) -> None:
        c_hash = item.data(FILE_HASH_ROLE)
        path = item.data(FILE_PATH_ROLE)
        repo = self._repo
        if not (c_hash and path and repo):
            return

        def job():
            return repo.commit_diff(c_hash, path)

        def done(result):
            if isinstance(result, Exception):
                return
            self.viewer_diff.show_diff(result or "")

        self.ctx.run_job(job, done)


def create_page(ctx) -> QWidget:
    return HistoryPage(ctx)


register(create_page, title="历史", order=20)
