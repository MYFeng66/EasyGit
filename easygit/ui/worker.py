# -*- coding: utf-8 -*-
"""后台执行器：git 操作一律异步，界面永不冻结（需求文档「规模与性能要求」）。"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class GitWorker(QThread):
    """在后台线程跑一个函数，结束后把结果（或异常）送回 UI 线程"""

    done = Signal(object)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self) -> None:
        try:
            result = self._fn(*self._args)
        except Exception as exc:  # 后台异常必须送到 UI，不能让线程无声死掉
            result = exc
        self.done.emit(result)


def run_async(fn, on_done, parent, keep: list) -> None:
    """在后台跑 fn，完成后回 UI 线程调 on_done(结果)。
    keep：外部的引用列表，防止 Python 侧被垃圾回收提前掐死线程；
    线程结束时自动从列表移除（否则每次点击泄漏一个引用）。"""
    worker = GitWorker(fn, parent=parent)
    worker.done.connect(on_done)

    def _cleanup():
        if worker in keep:
            keep.remove(worker)

    worker.finished.connect(worker.deleteLater)
    worker.finished.connect(_cleanup)
    keep.append(worker)
    worker.start()
