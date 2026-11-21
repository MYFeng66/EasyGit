# -*- coding: utf-8 -*-
"""「历史」页：提交历史树 v1（多色泳道 + 点 commit 看文件清单与 diff）。
对应需求文档 v1 #5 与第七章 3 的形态。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
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

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        self.label_count = QLabel("切换仓库后这里显示提交历史")
        self.label_count.setStyleSheet("color:#666;")
        btn_more = QPushButton("加载更多")
        btn_more.clicked.connect(lambda: self._load(more=True))
        btn_reload = QPushButton("刷新")
        btn_reload.clicked.connect(self.reload_from_ctx)
        bar.addWidget(self.label_count)
        bar.addStretch(1)
        bar.addWidget(btn_more)
        bar.addWidget(btn_reload)
        v.addLayout(bar)

        split = QSplitter(Qt.Horizontal)

        self.list = QListWidget()
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(GraphDelegate(self.list))
        self.list.itemClicked.connect(self._show_commit)
        self.list.verticalScrollBar().valueChanged.connect(self._on_scroll)
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
        rv.addWidget(self.list_files, 1)
        self.viewer_diff = DiffViewer()
        rv.addWidget(self.viewer_diff, 1)
        split.addWidget(right)
        split.setSizes([660, 420])
        v.addWidget(split, 1)

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
        if not self._repo or self._busy:
            return
        if not more:
            self._skip = 0
            self._commits = []
        self._busy = True
        repo = self._repo
        skip = self._skip

        def job():
            return repo.log(skip=skip, limit=self.PAGE)

        def done(result):
            self._busy = False
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
