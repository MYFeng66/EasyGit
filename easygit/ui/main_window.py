# -*- coding: utf-8 -*-
"""
主窗口：三区布局（需求文档 第六章）。
左栏仓库列表 ｜ 主区（工具栏 + 提示条 + 页签 + 提交条） ｜ 底部命令预览栏
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import features
from ..core import settings as settings_mod
from ..core.executor import CommandLog, translate_error
from ..core.git_wrapper import CommandRecord, GitRepo, StatusInfo
from ..core.shell import run_shell
from .add_repo_dialog import AddRepoDialog
from .branch_popup import BranchPopup
from .conflict_dialog import ConflictDialog
from .worker import run_async


# 工具栏分支名按钮的基础样式（含悬停反馈）
_BRANCH_BTN_STYLE = (
    "QPushButton{text-align:left;border:none;padding:2px 6px;}"
    "QPushButton:hover{background:#e2e2e2;border-radius:3px;}"
)


class MainWindow(QMainWindow):
    # 应用图标（随包分发，PyInstaller 友好）
    ICON = Path(__file__).resolve().parents[1] / "assets" / "easygit.ico"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyGit —— 你自己的 Git 管理器")
        if self.ICON.exists():
            self.setWindowIcon(QIcon(str(self.ICON)))
        self.resize(1080, 720)

        self.settings = settings_mod.load()
        self.log = CommandLog()
        self._workers: list = []        # 活跃后台线程引用（防垃圾回收）
        self.repo: GitRepo | None = None
        self.pages: dict[str, QWidget] = {}
        self._staged_count = 0          # 已勾选、将提交的文件数（驱动提交按钮）
        self._shown_log = 0             # 已写入日志面板的条数
        self._term_cwd = None            # 内嵌终端会话目录（cd 持久，切仓库时重置）
        self._last_status: StatusInfo | None = None    # 最近状态（守卫/推拉判断用）
        self._repo_has_remote = False    # 当前仓库有没有远端
        self._banner_action = None       # 提示条按钮当前动作
        self._detach_return_branch = None   # detached 查看前的原分支（一键回家）

        self._build_ui()
        self._reload_repos()

        # fetch 自动（第七章 2：只读零风险，每 5 分钟一次）
        self._fetch_timer = QTimer(self)
        self._fetch_timer.setInterval(5 * 60 * 1000)
        self._fetch_timer.timeout.connect(self._auto_fetch)
        self._fetch_timer.start()

    # ================================================ 界面搭建
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 工具栏：一切状态可见 ----
        bar = QWidget()
        bar.setObjectName("toolbar")   # 主题 QSS 由 theme.py 全局负责
        bar.setAttribute(Qt.WA_StyledBackground, True)   # 不加此属性背景色不会绘制
        hbar = QHBoxLayout(bar)
        hbar.setContentsMargins(8, 4, 8, 4)
        # 分支名本身可点（IDEA 式，用户标定 2026-11-21）：点击弹出分支弹窗
        self.label_branch = QPushButton("分支：— ▾")
        self.label_branch.setFlat(True)
        self.label_branch.setCursor(Qt.PointingHandCursor)
        self.label_branch.setStyleSheet(_BRANCH_BTN_STYLE)
        self.label_branch.setToolTip("点击弹出分支列表，单击切换（支持搜索）")
        self.label_branch.clicked.connect(self._open_branch_popup)
        self.label_ab = QLabel("")
        self.label_ab.setStyleSheet("color:#1565c0;")
        self.label_ab.setToolTip("领先远端 ↑ 的提交数 / 落后 ↓ 的提交数")
        btn_pull = QPushButton("拉取")
        btn_pull.setToolTip("fetch 之后合并：把远端新提交拿进来，融入当前分支")
        btn_pull.clicked.connect(self._pull)
        btn_push = QPushButton("推送")
        btn_push.setToolTip("把当前分支的新提交送到远端；首次推送自动建立关联")
        btn_push.clicked.connect(self._push)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setToolTip("重新读取仓库状态（不动任何文件）")
        btn_refresh.clicked.connect(self.refresh_status)
        btn_terminal = QPushButton("终端")
        btn_terminal.setToolTip("展开内嵌命令行（Git Bash），不弹外部窗口")
        btn_terminal.clicked.connect(self._open_embedded_terminal)
        hbar.addWidget(self.label_branch)
        hbar.addWidget(self.label_ab)
        hbar.addWidget(btn_pull)
        hbar.addWidget(btn_push)
        hbar.addWidget(btn_refresh)
        hbar.addStretch(1)
        hbar.addWidget(btn_terminal)
        root.addWidget(bar)

        # ---- 提示条（仅异常时出现，第六章 4） ----
        self.banner = QWidget()
        self.banner.setObjectName("banner")
        self.banner.setStyleSheet("QWidget#banner{background:#fff3cd;border-bottom:1px solid #e0c060;}")
        self.banner.setAttribute(Qt.WA_StyledBackground, True)
        hb = QHBoxLayout(self.banner)
        hb.setContentsMargins(8, 4, 8, 4)
        self.label_banner = QLabel("⚠")
        self.label_banner.setStyleSheet("color:#8a6d00;")
        btn_banner = QPushButton("去处理")
        self.btn_banner = btn_banner
        btn_banner.clicked.connect(self._banner_click)
        hb.addWidget(self.label_banner)
        hb.addStretch(1)
        hb.addWidget(btn_banner)
        self.banner.hide()
        root.addWidget(self.banner)

        # ---- 中部：左仓库列表 + 右页签 ----
        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        head = QLabel(" 仓库")
        head.setStyleSheet("font-weight:bold;padding:4px;")
        self.list_repo = QListWidget()
        self.list_repo.currentTextChanged.connect(self._select_repo)
        self.list_repo.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_repo.customContextMenuRequested.connect(self._repo_menu)
        btn_add = QPushButton("+ 添加仓库")
        btn_add.clicked.connect(self.add_repo)
        lv.addWidget(head)
        lv.addWidget(self.list_repo, 1)
        lv.addWidget(btn_add)
        split.addWidget(left)

        # 功能页（features 注册表驱动 —— 加/删功能不动这里）
        self.tabs = QTabWidget()
        for f in features.FEATURES:
            page = f["create"](self)
            self.pages[f["title"]] = page
            self.tabs.addTab(page, f["title"])
        split.addWidget(self.tabs)
        split.setSizes([180, 900])

        # ---- 提交条（第六章 3：固定底部、高度可拖动） ----
        commit_bar = QWidget()
        hc = QHBoxLayout(commit_bar)
        hc.setContentsMargins(8, 4, 8, 4)
        self.edit_msg = QLineEdit()
        self.edit_msg.setPlaceholderText("提交消息（一行写完）…")
        self.btn_commit = QPushButton("提交")
        self.btn_commit.setProperty("accent", True)   # git 橙主操作款（theme.py）
        self.btn_commit.setToolTip("把勾选的文件写入一条新提交；回车同效")
        self.btn_commit.setEnabled(False)   # 有勾选且有消息时激活
        self.btn_commit.clicked.connect(self._commit)
        self.edit_msg.textChanged.connect(self._update_commit_button)
        self.edit_msg.returnPressed.connect(self._commit)   # ≤3 秒流程：消息写完回车即提交
        hc.addWidget(self.edit_msg, 1)
        hc.addWidget(self.btn_commit)
        self.btn_undo = QPushButton("撤销 ▾")
        self.btn_undo.setToolTip("撤销上次提交（未推送）或反提交抵消（已推送）")
        undo_menu = QMenu(self)
        act_undo = undo_menu.addAction("撤销上次提交（改动保留，未推送时用）")
        act_revert = undo_menu.addAction("反提交抵消上次提交（已推送时用）")
        act_undo.triggered.connect(self._undo_last_commit)
        act_revert.triggered.connect(self._revert_last_commit)
        self.btn_undo.setMenu(undo_menu)
        hc.addWidget(self.btn_undo)

        # ---- 命令与日志栏：可展开如终端（第六章 5 升级，2026-11-20 标定） ----
        log_pane = QWidget()
        log_pane.setObjectName("logpane")
        log_pane.setStyleSheet("QWidget#logpane{background:#1e1e1e;}")
        log_pane.setAttribute(Qt.WA_StyledBackground, True)
        lvp = QVBoxLayout(log_pane)
        lvp.setContentsMargins(6, 2, 6, 4)
        lvp.setSpacing(2)

        head_row = QHBoxLayout()
        self.btn_log_toggle = QPushButton("▸ 命令与日志")
        self.btn_log_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_log_toggle.setStyleSheet(
            "QPushButton{color:#9cdcfe;font-weight:bold;border:none;background:transparent;}")
        self.btn_log_toggle.clicked.connect(self._toggle_log)
        self.label_cmd_text = QLabel("")
        # 关键修复：Ignored 策略——长命令文本不再把窗口最小宽度撑爆
        self.label_cmd_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 摘要行可选中复制（用户标定 2026-11-21）
        self.label_cmd_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label_cmd_text.setStyleSheet("color:#ccc;")
        head_row.addWidget(self.btn_log_toggle)
        head_row.addWidget(self.label_cmd_text, 1)
        lvp.addLayout(head_row)

        self.edit_log = QPlainTextEdit()
        self.edit_log.setReadOnly(True)
        self.edit_log.setStyleSheet(
            "QPlainTextEdit{background:#1a1a1a;color:#d4d4d4;"
            "font-family:Consolas,'Courier New',monospace;font-size:9pt;border:1px solid #333;}")
        self.edit_log.hide()
        lvp.addWidget(self.edit_log, 1)

        # 内嵌命令行：提示符 + 输入框（展开日志面板时可用）
        in_row = QHBoxLayout()
        prompt = QLabel("❯")
        prompt.setStyleSheet("color:#4ec9b0;font-weight:bold;font-family:Consolas,monospace;")
        self.edit_term = QLineEdit()
        self.edit_term.setPlaceholderText("输入命令，回车执行（ls/cat/grep 可用；clear 清屏；cd 切换目录）")
        self.edit_term.setStyleSheet(
            "QLineEdit{background:#1a1a1a;color:#d4d4d4;"
            "font-family:Consolas,monospace;border:1px solid #333;padding:2px 6px;}")
        self.edit_term.returnPressed.connect(self._run_typed_command)
        self.edit_term.hide()
        in_row.addWidget(prompt)
        in_row.addWidget(self.edit_term, 1)
        lvp.addLayout(in_row)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(split)
        vsplit.addWidget(commit_bar)
        vsplit.addWidget(log_pane)
        vsplit.setStretchFactor(0, 1)
        vsplit.setSizes([560, 60, 34])
        self._vsplit = vsplit   # 展开日志面板时同步调整分割配额
        root.addWidget(vsplit, 1)

        self.setCentralWidget(central)

    # ================================================ 仓库管理
    def _reload_repos(self) -> None:
        self.list_repo.blockSignals(True)
        self.list_repo.clear()
        for path in self.settings.get("repos", []):
            self.list_repo.addItem(path)
        self.list_repo.blockSignals(False)
        if self.list_repo.count():
            self.list_repo.setCurrentRow(0)   # 触发 _select_repo
        else:
            self.repo = None
            self._set_branch_text(None)
            page = self.pages.get("改动")
            if page:
                page.show_message("还没有打开仓库：点左下角「+ 添加仓库」")

    def _select_repo(self, path: str) -> None:
        if not path:
            return
        self.repo = GitRepo(path, self.log)
        self._term_cwd = path             # 切仓库时重置终端会话目录
        self._repo_has_remote = self.repo.has_remote()
        # 各功能页随仓库切换加载
        for key in ("历史", "分支", "对比"):
            page = self.pages.get(key)
            if page:
                page.reload(self.repo)
        self.setWindowTitle(f"EasyGit —— {path}")
        self._auto_fetch()                # 启动即取件一次（fetch 自动）
        self.refresh_status()

    def add_repo(self) -> None:
        """v1 #7：添加仓库向导（本地打开 / 从 URL 克隆，凭据走系统）"""
        dlg = AddRepoDialog(self)
        dlg.exec()
        path = dlg.result_path
        if not path:
            return
        repos = self.settings.setdefault("repos", [])
        if path not in repos:
            repos.append(path)
            settings_mod.save(self.settings)
        self._reload_repos()

    def _repo_menu(self, pos) -> None:
        """左栏仓库右键菜单（v1 #7 补全：取消托管）"""
        item = self.list_repo.itemAt(pos)
        if not item:
            return
        path = item.text()
        menu = QMenu(self)
        act = menu.addAction("取消托管（仅从列表移除，不删除磁盘仓库）")
        act.triggered.connect(lambda: self._remove_repo(path))
        menu.exec(self.list_repo.viewport().mapToGlobal(pos))

    def _remove_repo(self, path: str) -> None:
        """取消托管：从列表移除，磁盘上的仓库文件不受任何影响"""
        btn = QMessageBox.question(
            self, "取消托管",
            f"EasyGit 不再管理这个仓库：\n{path}\n\n"
            "仅从左侧列表移除；磁盘上的仓库文件不受任何影响。\n\n继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn != QMessageBox.Yes:
            return
        repos = self.settings.setdefault("repos", [])
        if path in repos:
            repos.remove(path)
            settings_mod.save(self.settings)
        self._reload_repos()

    def _open_embedded_terminal(self) -> None:
        """「终端」按钮 = 展开内嵌终端并聚焦输入行（用户标定 2026-11-21，不再弹外部窗口）"""
        if self.edit_term.isHidden():
            self._toggle_log()
        self.edit_term.setFocus()

    # ================================================ 功能页统一入口（统一执行管道）
    def run_git_job(self, fn, on_done=None) -> None:
        """后台执行一个 git 操作；完成后：报错大白话提示 → 自动刷新状态。
        fn(repo) -> CommandRecord；on_done(result) 总会先执行（result 可能是异常）。"""
        if not self.repo:
            return
        repo = self.repo

        def job():
            return fn(repo)

        def done(result):
            if on_done:
                on_done(result)              # 功能页自己的收尾（如解除 busy）总是执行
            if self.repo is not repo:          # 用户已切走仓库，丢弃过期结果
                return
            if isinstance(result, Exception):
                self.label_cmd_text.setStyleSheet("color:#f48771;")
                self.label_cmd_text.setText(f"操作失败：{result}")
                # 总改造一期：异常绝不沉默（今天两只 TypeError 的教训）。
                # 失败的 CommandRecord 已有大白话翻译，只沉命令栏；
                # 异常属意外情况（代码/环境问题），必须当面告知。
                QMessageBox.critical(
                    self, "操作失败",
                    "刚才的操作没有执行成功：\n\n"
                    f"{result}\n\n"
                    "详细信息在底部「命令与日志」栏。\n"
                    "如果反复出现，重启 EasyGit 后再试。")
                return
            if isinstance(result, CommandRecord) and not result.ok:
                first = result.output.splitlines()[0] if result.output else "执行失败"
                self.label_cmd_text.setStyleSheet("color:#f48771;")
                self.label_cmd_text.setText(
                    f"✗ {result.cmd} —— {translate_error(result.output) or first}")
                return
            self.refresh_status()

        run_async(job, done, parent=self, keep=self._workers)

    def run_job(self, fn, on_done) -> None:
        """后台跑任意函数（历史页等只读功能用）；不做状态刷新与错误翻译"""
        run_async(fn, on_done, parent=self, keep=self._workers)

    # ================================================ 状态刷新（异步，界面永不冻结）
    def refresh_status(self) -> None:
        if not self.repo:
            return
        repo = self.repo

        def job():
            return repo.status()

        def on_done(result):
            if self.repo is not repo:      # 用户已切走仓库，丢弃过期结果
                return
            if isinstance(result, Exception):
                self.label_cmd_text.setText(f"刷新失败：{result}")
                return
            self._render_status(result)

        run_async(job, on_done, parent=self, keep=self._workers)

    def _render_status(self, status: StatusInfo) -> None:
        # git status 失败（如 index.lock 冲突）：保留旧列表 + 报错，绝不说“工作区干净”
        if not status.ok:
            self.label_cmd_text.setStyleSheet("color:#f48771;")
            self.label_cmd_text.setText(
                f"✗ 读取改动失败 —— {status.error}")
            return
        self._last_status = status
        # 分支 + 领先/落后（工具栏）
        self._set_branch_text(status.branch)
        # 提示条：仅异常出现（第七章 4 触发规则）
        conflicts = [f for f in status.files if f.group == "conflict"]
        merging = bool(self.repo and self.repo.merge_in_progress())
        if conflicts:
            self._show_banner(
                f"⚠ 你处于合并冲突中：还剩 {len(conflicts)} 个文件没解决",
                "去处理", self._open_conflict_wizard)
        elif merging:
            self._show_banner(
                "⚠ 合并进行中：冲突文件都已标记解决，可完成合并提交",
                "去处理", self._open_conflict_wizard)
        elif status.branch.detached:
            ret = self._detach_return_branch
            if ret:
                self._show_banner(
                    "⚠ 你正在“看旧版本”（detached HEAD）——点右侧按钮随时回家",
                    f"回到 {ret}", lambda: self._switch_back(ret))
            else:
                self._show_banner(
                    "⚠ 你不在任何分支上（detached HEAD），提交可能丢",
                    "去分支页", lambda: self.tabs.setCurrentIndex(2))
        else:
            self.banner.hide()
        # 改动页 + 提交按钮 + 命令栏
        self._staged_count = sum(1 for f in status.files if f.group == "staged")
        self._update_commit_button()
        page = self.pages.get("改动")
        if page:
            page.refresh_from(status)
        self.label_cmd_text.setStyleSheet("color:#ccc;")
        self._sync_log_pane()

    # ================================================ 命令与日志面板（终端式）
    def _toggle_log(self) -> None:
        if self.edit_log.isHidden():
            self.edit_log.show()
            self.edit_term.show()
            self.edit_term.setFocus()
            self.btn_log_toggle.setText("▾ 命令与日志")
            self._vsplit.setSizes([500, 60, 220])   # 展开时给日志区让出高度
        else:
            self.edit_log.hide()
            self.edit_term.hide()
            self.btn_log_toggle.setText("▸ 命令与日志")
            self._vsplit.setSizes([560, 60, 34])    # 收起时还回去

    def _sync_log_pane(self) -> None:
        """把 CommandLog 里尚未显示的记录写入日志面板；摘要行只显示最近一条"""
        recs = list(self.log.records)
        for rec in recs[self._shown_log:]:
            mark = "OK  " if rec.ok else "FAIL"
            self.edit_log.appendPlainText(f"[{rec.time}] {mark} {rec.cmd}")
            if rec.output and (rec.show_output or not rec.ok):
                lines = rec.output.splitlines()[:200]   # 超长输出截断保护
                for line in lines:
                    self.edit_log.appendPlainText("      " + line)
        self._shown_log = len(recs)
        self.label_cmd_text.setText(recs[-1].cmd if recs else "")

    def _run_typed_command(self) -> None:
        """内嵌命令行：执行用户输入的命令（clear 清屏、cd 持久，贴近真终端手感）"""
        text = self.edit_term.text().strip()
        if not text or not self.repo:
            return
        cwd = self._term_cwd or self.repo.path

        # 屏幕类命令拦截：日志面板是文本框不是屏幕，clear 的转义码在这里没有意义
        if text in ("clear", "cls"):
            self.edit_term.clear()
            self.edit_log.clear()
            return
        if text == "cd" or text.startswith("cd "):
            self._cd_session(cwd, text[3:].strip() if len(text) > 2 else None)
            self.edit_term.clear()
            return

        self.edit_term.clear()
        self.edit_term.setEnabled(False)   # 执行期间锁定输入

        def job():
            return run_shell(cwd, text)

        def done(result):
            self.edit_term.setEnabled(True)
            self.edit_term.setFocus()
            if isinstance(result, Exception):
                self.log.add(CommandRecord(cmd=f"$ {text}", ok=False,
                                           output=str(result)))
            else:
                self.log.add(result)
            self._sync_log_pane()
            # 手敲的 git 命令也可能改了仓库状态 → 顺手刷新
            if text.split()[0] == "git":
                self.refresh_status()
                if text.startswith("git commit"):
                    history = self.pages.get("历史")
                    if history:
                        history.reload(self.repo)

        run_async(job, done, parent=self, keep=self._workers)

    def _cd_session(self, cwd: str, target: str | None) -> None:
        """内嵌终端的 cd：切换会话工作目录；不带参数 = 回仓库根目录"""
        if target is None:
            self._term_cwd = self.repo.path
            self.edit_log.appendPlainText(f"$ cd  →  {self._term_cwd}")
            return
        argv_path = target.replace("\\", "/")   # bash 只认正斜杠
        self.edit_term.setEnabled(False)

        def job():
            # pwd -W 是 Git Bash 扩展：输出 Windows 形式路径
            return run_shell(cwd, f"cd {argv_path} && pwd -W")

        def done(result):
            self.edit_term.setEnabled(True)
            self.edit_term.setFocus()
            if isinstance(result, Exception):
                self.log.add(CommandRecord(cmd=f"$ cd {target}", ok=False,
                                           output=str(result)))
                self._sync_log_pane()
                return
            if not result.ok:
                self.log.add(result)
                self._sync_log_pane()
                return
            new_cwd = result.output.strip().splitlines()[-1]
            self._term_cwd = new_cwd
            self.edit_log.appendPlainText(f"$ cd {target}  →  {new_cwd}")

        run_async(job, done, parent=self, keep=self._workers)

    # ================================================ 提交（≤3 秒流程）
    def _update_commit_button(self) -> None:
        has_msg = bool(self.edit_msg.text().strip())
        n = self._staged_count
        self.btn_commit.setEnabled(n > 0 and has_msg)
        self.btn_commit.setText(f"提交（{n} 个文件）" if n else "提交")

    def _commit(self) -> None:
        msg = self.edit_msg.text().strip()
        if not msg or not self.repo:
            return
        self.btn_commit.setEnabled(False)

        def on_done(rec):
            if isinstance(rec, CommandRecord) and rec.ok:
                self.edit_msg.clear()   # 提交成功后清空消息；状态由自动刷新更新
                history = self.pages.get("历史")
                if history:
                    history.reload(self.repo)   # 历史树同步最新提交

        self.run_git_job(lambda repo: repo.commit(msg), on_done)

    # ================================================ 撤销三件套（v1 #2 后半，痛点 C）
    def _undo_last_commit(self) -> None:
        """撤销上次提交：改动回到「已勾选」。已推送则拦下并引导改用反提交（防呆：避免本地与远端分叉）"""
        if not self.repo:
            return
        repo = self.repo

        def check():
            return repo.is_head_pushed()

        def on_checked(result):
            if isinstance(result, Exception):
                return
            if result:
                QMessageBox.information(
                    self, "上次提交已推送",
                    "上次提交已经在远端了，直接撤销会让本地和远端分叉。\n\n"
                    "请改用菜单第二项「反提交抵消上次提交」：\n"
                    "它产生一个新的抵消提交，正常推送即可，历史不会被改写。")
                return

            def job(repo):
                # run_git_job 的约定：fn(repo)
                return repo.undo_last_commit()

            def on_done(rec):
                if isinstance(rec, CommandRecord) and rec.ok:
                    history = self.pages.get("历史")
                    if history:
                        history.reload(self.repo)

            self.run_git_job(job, on_done)

        self.run_job(check, on_checked)

    def _revert_last_commit(self) -> None:
        """反提交抵消上次提交（第八章：需确认并解释「产生新提交，非删历史」）"""
        if not self.repo:
            return
        btn = QMessageBox.question(
            self, "确认反提交",
            "这会产生一个新的「抵消提交」，效果上撤销上次提交的全部改动。\n"
            "历史不会被删除（已推送的提交本来也不该删），推送后远端同步。\n\n"
            "继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn != QMessageBox.Yes:
            return

        def job(repo):
            # run_git_job 的约定：fn(repo)
            return repo.revert_last_commit()

        def on_done(rec):
            if isinstance(rec, CommandRecord) and rec.ok:
                history = self.pages.get("历史")
                if history:
                    history.reload(self.repo)

        self.run_git_job(job, on_done)

    # ================================================ 提示条与远程同步（v1 #3/#6）
    def _banner_click(self) -> None:
        if self._banner_action:
            self._banner_action()

    def _show_banner(self, text: str, btn_text: str, action) -> None:
        self.label_banner.setText(text)
        self.btn_banner.setText(btn_text)
        self._banner_action = action
        self.banner.show()

    def _auto_fetch(self) -> None:
        """fetch 自动（第七章 2）：只更新记账副本，不动你的任何东西"""
        if not (self.repo and self._repo_has_remote):
            return
        repo = self.repo

        def job():
            return repo.fetch()

        def done(result):
            if self.repo is repo and not isinstance(result, Exception):
                self.refresh_status()   # 取件后 ↑↓ 更新

        self.run_job(job, done)

    def _pull(self) -> None:
        """拉取 = 取件 + 合并进当前分支；永远手动，有未提交改动先警告（第七章 2）"""
        if not self.repo:
            return
        st = self._last_status
        if st and any(f.group in ("staged", "unstaged") for f in st.files):
            btn = QMessageBox.question(
                self, "有未提交改动",
                "你有未提交的改动，拉取可能产生冲突。\n"
                "建议先提交再拉取（改动页勾选 → 提交）。\n\n仍要继续拉取吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if btn != QMessageBox.Yes:
                return

        def on_done(rec):
            if isinstance(rec, CommandRecord) and rec.ok:
                history = self.pages.get("历史")   # pull 可能产生合并提交
                if history:
                    history.reload(self.repo)

        self.run_git_job(lambda repo: repo.pull(), on_done)

    def _push(self) -> None:
        """推送；当前分支未关联远端时自动建立关联（push -u，E 类痛点一键化）"""
        if not self.repo:
            return
        st = self._last_status
        upstream = st.branch.upstream if st else None

        def job(repo):
            return repo.push_set_upstream() if not upstream else repo.push()

        def on_done(rec):
            if isinstance(rec, CommandRecord) and not rec.ok \
                    and "non-fast-forward" in rec.output:
                self._show_banner("⚠ 远端有你没有的新提交，先拉取",
                                  "去拉取", self._pull)

        self.run_git_job(job, on_done)

    def _open_conflict_wizard(self) -> None:
        """冲突解决向导（v1 #6，痛点 A）"""
        if not self.repo:
            return
        dlg = ConflictDialog(self.repo, self)
        dlg.exec()
        # 向导可能产生了合并提交
        history = self.pages.get("历史")
        if history:
            history.reload(self.repo)
        self.refresh_status()

    # ================================================ 工具栏分支弹窗（IDEA 式，用户标定 2026-11-21）
    def _open_branch_popup(self) -> None:
        """点击工具栏分支名 → 搜索 + 滚动 + 右键菜单的分支弹窗（限高，80+ 分支不占屏）"""
        if not self.repo:
            return
        repo = self.repo

        def job():
            return repo.branches()

        def done(result):
            if isinstance(result, Exception) or not result:
                return
            branch_page = self.pages.get("分支")
            if not branch_page:
                return
            local, remote = result
            popup = BranchPopup(branch_page, self)
            popup.refresh(local, remote)
            popup.move(self.label_branch.mapToGlobal(
                self.label_branch.rect().bottomLeft()))
            popup.show()
            popup.raise_()
            popup.edit_search.setFocus()

        self.run_job(job, done)

    def _switch_back(self, branch_name: str) -> None:
        """detached 查看后一键回家"""
        self._detach_return_branch = None
        self.run_git_job(lambda repo: repo.switch_branch(branch_name), None)

    def _set_branch_text(self, branch) -> None:
        if branch is None or (not branch.name and not branch.detached):
            self.label_branch.setText("分支：— ▾")
            self.label_branch.setStyleSheet(_BRANCH_BTN_STYLE)
            self.label_ab.setText("")
            return
        if branch.detached:
            self.label_branch.setText("HEAD 游离（不在任何分支上） ▾")
            self.label_branch.setStyleSheet(
                _BRANCH_BTN_STYLE + "QPushButton{color:#c0392b;}")
        else:
            self.label_branch.setText(f"{branch.name} ▾")
            self.label_branch.setStyleSheet(_BRANCH_BTN_STYLE)
        if branch.upstream:
            self.label_ab.setText(f"↑{branch.ahead} ↓{branch.behind}")
        else:
            self.label_ab.setText("未关联远端")
