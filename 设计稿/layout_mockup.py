# -*- coding: utf-8 -*-
"""
EasyGit 主界面布局草案（静态假数据可视化）
用途：把"三区布局"画出来讨论，不是功能实现。
运行：.venv\\Scripts\\python 设计稿\\layout_mockup.py
截图：QT_QPA_PLATFORM=offscreen 时自动保存 layout_mockup.png
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

# ---------------- 通用小工具 ----------------

def label(text, color=None, bold=False, size=None):
    """快速造一个 QLabel"""
    lab = QLabel(text)
    style = ""
    if color:
        style += f"color:{color};"
    if bold:
        style += "font-weight:bold;"
    if size:
        style += f"font-size:{size}pt;"
    if style:
        lab.setStyleSheet(style)
    return lab


def group_header(text, color=None):
    """分组标题：粗体 + 底部一条浅色分隔线"""
    lab = label(text, color=color, bold=True)
    lab.setStyleSheet(
        "font-weight:bold;border-bottom:1px solid #d0d0d0;padding:2px 0;"
        + (f"color:{color};" if color else "")
    )
    return lab


def file_row(name, stat, checked=False, stat_color="#2e7d32", red=False):
    """改动页的一行文件：勾选框 + 文件名 + 变更量"""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(4, 0, 4, 0)
    h.setSpacing(8)
    box = QCheckBox()
    box.setChecked(checked)
    name_lab = label(name, color="#c0392b" if red else None)
    name_lab.setMinimumWidth(140)
    h.addWidget(box)
    h.addWidget(name_lab)
    h.addStretch(1)
    h.addWidget(label(stat, color=stat_color))
    if red:  # 已退库（新发现）行带「我知道了」按钮
        h.addWidget(QPushButton("我知道了"))
    return row


# ---------------- 改动页 ----------------

def make_change_page():
    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(4)

    # 顶部操作行
    top = QHBoxLayout()
    top.addWidget(label("勾选要提交的改动", bold=True))
    top.addWidget(label("（点文件名 → 右侧滑出 diff 面板）", color="#888888"))
    top.addStretch(1)
    top.addWidget(QPushButton("全选"))
    top.addWidget(QPushButton("全不选"))
    v.addLayout(top)

    # 七个分组（对应需求文档「状态面板分组规格」）
    v.addWidget(group_header("☑ 已勾选、将提交（2）—— 点「提交」就会生效的内容"))
    v.addWidget(file_row("src/app.py", "+12 −4", checked=True))
    v.addWidget(file_row("style.css", "+2", checked=True))

    v.addWidget(group_header("☐ 改了、未勾选（1）—— 改了，还没勾进本次提交"))
    v.addWidget(file_row("README.md", "+2"))

    v.addWidget(group_header("☐ 未跟踪（1）—— 新文件，还没进过版本库"))
    v.addWidget(file_row("draft.md", "新文件"))

    v.addWidget(group_header("已退库 · 新发现（1）—— 以前在仓库里，现已退库，不会再同步", color="#c0392b"))
    v.addWidget(file_row("config.py", "已退库", stat_color="#c0392b", red=True))

    # 三个可折叠的次要分组，一行展示（颜色区分，不用 emoji）
    fold = QHBoxLayout()
    for text, col in (
        ("已退库 · 已知晓（1）▸", "#777777"),
        ("仅本地（1）▸", "#b8860b"),
        ("被忽略（3）▸", "#777777"),
    ):
        fold.addWidget(label(text, color=col))
    fold.addStretch(1)
    v.addLayout(fold)

    v.addStretch(1)
    return page


# ---------------- 历史页 ----------------

def make_history_page():
    page = QWidget()
    h = QHBoxLayout(page)
    h.setContentsMargins(8, 8, 8, 8)

    # 左：commit 列表（假数据，冒充提交图）
    left = QWidget()
    lv = QVBoxLayout(left)
    lv.setContentsMargins(0, 0, 0, 0)
    lv.addWidget(label("历史图（分页加载：显示最近 50 条） [搜索/过滤分支 ▾]", bold=True))
    commits = QListWidget()
    for text in (
        "● a1f2e3  修复登录跳转   张三 · 2 小时前",
        "● b3c4d5  更新依赖版本   李四 · 4 小时前",
        "●  c6d7e8  初始化脚手架  王五 · 昨天",
    ):
        commits.addItem(QListWidgetItem(text))
    lv.addWidget(commits)
    h.addWidget(left, 55)

    # 右：commit 详情占位
    right = label("点左侧某个提交 →\n这里显示它的文件清单与 diff", color="#888888")
    right.setAlignment(Qt.AlignCenter)
    h.addWidget(right, 45)
    return page


# ---------------- 分支页 ----------------

def make_branch_page():
    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(8, 8, 8, 8)

    v.addWidget(QLineEdit(placeholderText="搜索分支…（对付几十条远端分支）"))

    tree = QTreeWidget()
    tree.setHeaderLabels(["分支", "跟踪的远端分支", "领先 / 落后", "操作"])

    local = QTreeWidgetItem(["本地（2）"])
    QTreeWidgetItem(local, ["main", "跟踪 origin/main", "↑2 ↓1", "右键：删除/合并"])
    QTreeWidgetItem(local, ["feature-login", "跟踪 origin/feature-login", "↑0 ↓3", ""])
    tree.addTopLevelItem(local)

    remote = QTreeWidgetItem(["远端（3）"])
    QTreeWidgetItem(remote, ["origin/main", "—", "", "右键：检出为新本地分支"])
    QTreeWidgetItem(remote, ["origin/feature-login", "—", "", ""])
    QTreeWidgetItem(remote, ["origin/dev", "—", "", ""])
    tree.addTopLevelItem(remote)

    tree.expandAll()
    v.addWidget(tree)
    v.addWidget(label("切分支时若检测到未提交改动 → 弹出「切分支守卫」对话框", color="#888888"))
    return page


# ---------------- 对比页 ----------------

def make_compare_page():
    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(8, 8, 8, 8)

    row = QHBoxLayout()
    row.addWidget(label("对比："))
    a = QComboBox(); a.addItems(["main"])
    b = QComboBox(); b.addItems(["feature-login"])
    row.addWidget(a)
    row.addWidget(label("vs"))
    row.addWidget(b)
    row.addStretch(1)
    v.addLayout(row)

    tree = QTreeWidget()
    tree.setHeaderLabels(["路径", "状态"])

    src = QTreeWidgetItem(["src/"])
    QTreeWidgetItem(src, ["app.py", "修改 ~"])
    QTreeWidgetItem(src, ["legacy.py", "删除 −"])
    tree.addTopLevelItem(src)
    QTreeWidgetItem(tree, ["docs/guide.md  （新增 +）"])

    tree.expandAll()
    v.addWidget(tree)
    v.addWidget(label("点文件 → 显示两个分支间该文件的 diff", color="#888888"))
    return page


# ---------------- 主窗口 ----------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyGit — 界面布局草案（静态假数据）")
        self.resize(1080, 720)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 工具栏：永远可见的状态 ----
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setStyleSheet("QWidget#toolbar{background:#f0f0f0;border-bottom:1px solid #cccccc;}")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 4)
        h.addWidget(label("仓库：EasyGit ▾", bold=True))
        h.addWidget(label("分支：main ▾", bold=True))
        h.addWidget(label("↑2 ↓1", color="#1565c0"))
        h.addWidget(QPushButton("拉取"))
        h.addWidget(QPushButton("推送"))
        h.addStretch(1)
        h.addWidget(QPushButton("检测退库"))
        h.addWidget(QPushButton("打开终端"))
        root.addWidget(bar)

        # ---- 提示条（仅异常时出现，此处展示形态） ----
        banner = QWidget()
        banner.setObjectName("banner")
        banner.setStyleSheet("QWidget#banner{background:#fff3cd;border-bottom:1px solid #e0c060;}")
        banner.setAttribute(Qt.WA_StyledBackground, True)
        bh = QHBoxLayout(banner)
        bh.setContentsMargins(8, 4, 8, 4)
        bh.addWidget(label("⚠ 你处于合并冲突中：还剩 2 个文件没解决（此条仅异常时出现）", color="#8a6d00"))
        bh.addStretch(1)
        bh.addWidget(QPushButton("去处理"))
        root.addWidget(banner)

        # ---- 中部：左仓库列表 + 右四页签 ----
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        repos = QListWidget()
        repos.addItem("⭐ EasyGit")
        repos.addItem("   blog")
        repos.addItem("   bigproj")
        lv.addWidget(label(" 仓库列表", bold=True))
        lv.addWidget(repos)
        lv.addWidget(QPushButton("+ 添加仓库"))
        split.addWidget(left)

        tabs = QTabWidget()
        tabs.addTab(make_change_page(), "改动")
        tabs.addTab(make_history_page(), "历史")
        tabs.addTab(make_branch_page(), "分支")
        tabs.addTab(make_compare_page(), "对比")
        split.addWidget(tabs)
        split.setSizes([170, 900])
        # ---- 提交条（固定不随页签消失，高度可拖动） ----
        commit_bar = QWidget()
        ch = QHBoxLayout(commit_bar)
        ch.setContentsMargins(8, 4, 8, 4)
        msg = QLineEdit(placeholderText="提交消息（一行写完）…")
        ch.addWidget(msg, 1)
        btn = QPushButton("提交（2 个文件）")
        btn.setStyleSheet("font-weight:bold;padding:4px 12px;")
        ch.addWidget(btn)

        # 主区与提交条之间用 QSplitter：拖动分割线即可调提交条高度
        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(split)
        vsplit.addWidget(commit_bar)
        vsplit.setStretchFactor(0, 1)
        vsplit.setSizes([560, 70])
        root.addWidget(vsplit, 1)

        # ---- 命令预览与日志栏 ----
        cmd_bar = QWidget()
        cmd_bar.setObjectName("cmdbar")
        cmd_bar.setStyleSheet("QWidget#cmdbar{background:#1e1e1e;}")
        cmd_bar.setAttribute(Qt.WA_StyledBackground, True)
        cc = QHBoxLayout(cmd_bar)
        cc.setContentsMargins(8, 3, 8, 3)
        cc.addWidget(label("▾ 命令预览与日志", color="#9cdcfe", bold=True))
        cc.addWidget(label("git add src/app.py  ·  git commit -m \"修复登录\"  ✓ 成功", color="#cccccc"))
        cc.addStretch(1)
        root.addWidget(cmd_bar)

        self.setCentralWidget(central)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    win = MainWindow()
    win.show()
    app.processEvents()

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout_mockup.png")
    win.grab().save(out)
    print("已保存截图:", out)

    if "--interactive" in sys.argv:
        sys.exit(app.exec())  # 加 --interactive 参数则真弹窗可点


if __name__ == "__main__":
    main()
