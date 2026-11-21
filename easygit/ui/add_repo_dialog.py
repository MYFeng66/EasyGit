# -*- coding: utf-8 -*-
"""添加仓库向导（v1 #7，痛点 D）：两种方式 —— 打开本地已有仓库 / 从 URL 克隆。
平台选择（GitHub / Gitee / Codeup / GitLab）只是帮你预填 URL 样例：
git 本身与平台无关，凭据由 Windows 凭据管理器自动接管。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core.git_wrapper import clone_repo
from .worker import run_async

PLATFORM_URL_HINTS = {
    "GitHub": "https://github.com/用户名/仓库.git",
    "Gitee": "https://gitee.com/用户名/仓库.git",
    "Codeup": "https://codeup.aliyun.com/组织/仓库.git",
    "GitLab": "https://gitlab.com/用户名/仓库.git",
    "自定义 URL": "https://代码托管平台/仓库.git",
}


class AddRepoDialog(QDialog):
    """成功后 result_path = 仓库本地路径；取消则为 None。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_path: str | None = None
        self._workers: list = []

        self.setWindowTitle("添加仓库")
        self.resize(560, 300)

        v = QVBoxLayout(self)
        v.setSpacing(8)

        combo_mode = QComboBox()
        combo_mode.addItems(["打开本地已有的仓库", "从 URL 克隆远程仓库"])
        combo_mode.currentIndexChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        v.addWidget(combo_mode)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # ---- 方式一：本地文件夹 ----
        page_local = QWidget()
        lv = QVBoxLayout(page_local)
        lv.setContentsMargins(0, 8, 0, 0)
        lv.setSpacing(8)
        self.label_local = QLabel("还没选择文件夹")
        lv.addWidget(self.label_local)
        btn_pick = QPushButton("选择仓库文件夹…")
        btn_pick.clicked.connect(self._pick_local)
        lv.addWidget(btn_pick)
        lv.addStretch(1)
        self.stack.addWidget(page_local)

        # ---- 方式二：克隆 ----
        page_clone = QWidget()
        cv = QVBoxLayout(page_clone)
        cv.setContentsMargins(0, 8, 0, 0)
        cv.setSpacing(8)

        combo_platform = QComboBox()
        combo_platform.addItems(PLATFORM_URL_HINTS.keys())
        cv.addWidget(combo_platform)

        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText(PLATFORM_URL_HINTS["GitHub"])
        combo_platform.currentTextChanged.connect(
            lambda name: self.edit_url.setPlaceholderText(PLATFORM_URL_HINTS[name]))
        cv.addWidget(self.edit_url)

        hint = QLabel("克隆到（默认 ~/EasyGitRepos/仓库名）：")
        hint.setStyleSheet("color:#888;")
        cv.addWidget(hint)
        btn_clone = QPushButton("开始克隆")
        btn_clone.setStyleSheet("font-weight:bold;")
        btn_clone.clicked.connect(self._start_clone)
        cv.addWidget(btn_clone)
        self.label_clone_status = QLabel("")
        self.label_clone_status.setWordWrap(True)
        self.label_clone_status.setStyleSheet("color:#888;")
        cv.addWidget(self.label_clone_status)
        cv.addStretch(1)
        self.stack.addWidget(page_clone)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        v.addLayout(row)

    # ================================================ 本地方式
    def _pick_local(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择仓库文件夹")
        if path:
            self.result_path = path
            self.label_local.setText(path)
            self.accept()

    # ================================================ 克隆方式
    def _start_clone(self) -> None:
        url = self.edit_url.text().strip()
        if not url:
            self.label_clone_status.setText("请先填 URL（照着灰字样例的样子）")
            self.label_clone_status.setStyleSheet("color:#c0392b;")
            return
        base = url.rstrip("/").split("/")[-1]
        base = base[:-4] if base.endswith(".git") else base
        base = base or "repo"
        target = str(Path.home() / "EasyGitRepos" / base)

        self.label_clone_status.setStyleSheet("color:#888;")
        self.label_clone_status.setText(f"正在克隆到 {target} …（大仓库可能要几分钟）")

        def job():
            return clone_repo(url, target)

        def done(rec):
            if isinstance(rec, Exception):
                self.label_clone_status.setText(f"克隆失败：{rec}")
                return
            if not rec.ok:
                first = rec.output.splitlines()[-1] if rec.output else "执行失败"
                self.label_clone_status.setText(f"克隆失败：{first}")
                self.label_clone_status.setStyleSheet("color:#c0392b;")
                return
            self.result_path = target
            self.accept()

        run_async(job, done, parent=self, keep=self._workers)
