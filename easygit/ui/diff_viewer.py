# -*- coding: utf-8 -*-
"""diff / 源码 / 预览 公共查看器（v1 #1/#5/#9 共用，需求文档「关键功能规格 4」）。

渲染方案：pygments 生成**内联样式**的 HTML → Qt 富文本直接显示。
不引入浏览器引擎（技术选型红线）；Markdown 用 markdown 库 + Qt 富文本。
"""

from __future__ import annotations

import markdown as md
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DiffLexer, TextLexer, guess_lexer_for_filename
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

STYLE = "default"


def _pygments_html(text: str, lexer) -> str:
    if not text:
        return ""
    formatter = HtmlFormatter(noclasses=True, nowrap=True, style=STYLE)
    # noclasses+nowrap：只产出带内联样式的 <span> 序列，Qt 富文本最兼容
    return f"<pre>{highlight(text, lexer, formatter)}</pre>"


def render_diff_html(diff_text: str) -> str:
    """统一 diff：+ 行绿、− 行红、@@ 蓝粗（pygments DiffLexer 内建规则）"""
    return _pygments_html(diff_text, DiffLexer())


def render_source_html(path: str, text: str) -> str:
    """文件源码：按后缀猜语言上色；猜不中按纯文本"""
    try:
        lexer = guess_lexer_for_filename(path, text)
    except Exception:
        lexer = TextLexer()
    return _pygments_html(text, lexer)


def render_markdown_html(text: str) -> str:
    """Markdown → HTML（Qt 富文本支持标题/列表/代码块/表格的基本排版）"""
    return md.markdown(text, extensions=["fenced_code", "tables", "nl2br"])


class DiffViewer(QWidget):
    """右侧查看器：diff（+绿 −红）/ 源码（按后缀高亮）/ Markdown 预览，三模式切换。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._diff = ""
        self._source: str | None = None
        self._mode = "diff"

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 3, 6, 3)
        bar.addWidget(QLabel("查看："))
        self.btn_diff = QPushButton("diff")
        self.btn_source = QPushButton("源码")
        self.btn_preview = QPushButton("预览")
        for b in (self.btn_diff, self.btn_source, self.btn_preview):
            b.setCursor(Qt.PointingHandCursor)
            b.setCheckable(True)
            bar.addWidget(b)
        bar.addStretch(1)
        self.btn_diff.clicked.connect(lambda: self._set_mode("diff"))
        self.btn_source.clicked.connect(lambda: self._set_mode("source"))
        self.btn_preview.clicked.connect(lambda: self._set_mode("preview"))
        v.addLayout(bar)

        self.edit = QTextEdit()
        self.edit.setReadOnly(True)
        v.addWidget(self.edit, 1)

        self.clear_view()

    # ================================================ 对外接口
    def clear_view(self) -> None:
        self._path = ""
        self._diff = ""
        self._source = None
        for b in (self.btn_diff, self.btn_source, self.btn_preview):
            b.setVisible(False)
            b.setChecked(False)
        self.edit.clear()
        self._hint("点左侧文件名，这里显示 diff / 源码 / 预览")

    def show_diff(self, diff_text: str) -> None:
        """单模式入口：只显示一份 diff（历史页用）"""
        self._path = ""
        self._source = None
        self._diff = diff_text or ""
        self.btn_diff.setVisible(True)
        self.btn_source.setVisible(False)
        self.btn_preview.setVisible(False)
        self._set_mode("diff")

    def set_content(self, path: str, diff_text: str,
                    source_text: str | None) -> None:
        """三模式入口：改动页用。.md 文件额外出现「预览」；
        没有差异（未跟踪新文件）时默认直接看源码/预览。"""
        self._path = path
        self._diff = diff_text or ""
        self._source = source_text
        is_md = path.lower().endswith((".md", ".markdown"))
        self.btn_diff.setVisible(True)
        self.btn_source.setVisible(source_text is not None)
        self.btn_preview.setVisible(is_md and source_text is not None)
        if self._diff:
            mode = "diff"
        elif source_text is not None:
            mode = "source"
        else:
            mode = "diff"
        self._set_mode(mode)

    # ================================================ 内部渲染
    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self.btn_diff.setChecked(mode == "diff")
        self.btn_source.setChecked(mode == "source")
        self.btn_preview.setChecked(mode == "preview")

        if mode == "diff":
            self.edit.setFont(QFont("Consolas", 9))
            if self._diff:
                self.edit.setHtml(render_diff_html(self._diff))
            else:
                self._hint("（没有可显示的差异）")
        elif mode == "source":
            self.edit.setFont(QFont("Consolas", 9))
            if self._source:
                self.edit.setHtml(render_source_html(self._path, self._source))
            else:
                self._hint("（读不到源码——文件可能已删除）")
        else:  # 预览
            self.edit.setFont(QFont("Microsoft YaHei UI", 10))
            if self._source:
                self.edit.setHtml(render_markdown_html(self._source))
            else:
                self._hint("（读不到源码）")

    def _hint(self, text: str) -> None:
        self.edit.setHtml(f"<p style='color:#888888'>{text}</p>")
