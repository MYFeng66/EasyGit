# -*- coding: utf-8 -*-
"""
EasyGit 全局主题：现代扁平化（2026-11-21 总改造一期）。

设计令牌
--------
表面    : 纯白内容区 / #f7f8fa 铬件（工具栏、表头）
文字    : #24292f 主 / #57606a 次
描边    : #d0d7de 常规 / #e4e7eb 弱
强调色  : git 橙 #F05032（主操作按钮、页签指示线、聚焦边框）
圆角    : 6px 控件 / 8px 菜单 / 4px 列表条目

应用方式 : __main__ 里 apply_theme(app)，一处生效全局。
暗色区（命令栏/终端/日志）由各自内联样式负责，不在此处。
"""

from __future__ import annotations

QSS = """
/* ---------- 基础 ---------- */
QMainWindow, QDialog { background: #ffffff; }
QLabel { color: #24292f; background: transparent; }

/* ---------- 工具栏铬件 ---------- */
QWidget#toolbar { background: #f7f8fa; border-bottom: 1px solid #e4e7eb; }

/* ---------- 按钮：默认静音款 ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 5px 14px;
    color: #24292f;
}
QPushButton:hover { background: #f3f4f6; }
QPushButton:pressed { background: #e9ebee; }
QPushButton:disabled { color: #9aa0a6; background: #f6f8fa; border-color: #eaeef2; }
QPushButton:menu-indicator { width: 0; }

/* 主操作款（setProperty("accent", True)）：git 橙 */
QPushButton[accent="true"] {
    background: #F05032; border: 1px solid #F05032;
    color: #ffffff; font-weight: 600;
}
QPushButton[accent="true"]:hover { background: #d94529; }
QPushButton[accent="true"]:pressed { background: #c23d22; }
QPushButton[accent="true"]:disabled { background: #f6b3a5; border-color: #f6b3a5; }

/* ---------- 输入与列表 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 4px 8px;
    color: #24292f;
    selection-background-color: #fdeae4;
}
QLineEdit:focus { border: 1px solid #F05032; }

QListWidget, QTreeWidget, QTreeView {
    background: #ffffff;
    border: 1px solid #e4e7eb;
    border-radius: 6px;
    outline: 0;
}
QListWidget::item, QTreeWidget::item { border-radius: 4px; }
QListWidget::item:hover { background: #f6f8fa; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #fdeae4; color: #24292f; }

/* ---------- 页签：下划线式，去掉默认大框 ---------- */
QTabWidget::pane { border: none; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    padding: 7px 18px;
    color: #57606a;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { color: #24292f; }
QTabBar::tab:selected { color: #F05032; border-bottom: 2px solid #F05032; font-weight: 600; }

/* ---------- 表头 ---------- */
QHeaderView::section {
    background: #f7f8fa; border: none;
    border-bottom: 1px solid #e4e7eb;
    padding: 6px; color: #57606a;
}

/* ---------- 菜单 ---------- */
QMenu { background: #ffffff; border: 1px solid #e4e7eb; border-radius: 8px; padding: 6px 2px; }
QMenu::item { padding: 6px 26px 6px 14px; border-radius: 4px; color: #24292f; }
QMenu::item:selected { background: #f6f8fa; }
QMenu::separator { height: 1px; background: #eaeef2; margin: 4px 8px; }

/* ---------- 滚动条：细瘦圆润 ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #d0d7de; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #b6bec6; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #d0d7de; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #b6bec6; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------- 分割条 ---------- */
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: #e4e7eb; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }

/* ---------- 工具提示 ---------- */
QToolTip {
    background: #24292f; color: #ffffff;
    border: none; padding: 5px 8px; border-radius: 4px;
}
"""


def apply_theme(app) -> None:
    """在 QApplication 上启用全局主题（见 __main__）。"""
    app.setStyleSheet(QSS)
