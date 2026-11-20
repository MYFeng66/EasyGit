# -*- coding: utf-8 -*-
"""统一执行管道（雏形）：预览 → 执行 → 记日志。
所有“用户点按钮 → git 执行”最终都汇到 CommandLog（需求文档 第二章 机制 3）。"""

from __future__ import annotations

from collections import deque

from .git_wrapper import CommandRecord


class CommandLog:
    """命令预览/日志栏的数据源：全部 git 调用的流水账"""

    def __init__(self, maxlen: int = 200):
        self.records: deque[CommandRecord] = deque(maxlen=maxlen)

    def add(self, rec: CommandRecord) -> None:
        self.records.append(rec)

    def tail_text(self, n: int = 3) -> str:
        """命令预览栏显示用：最近 n 条，一行内并列展示"""
        items = []
        for rec in list(self.records)[-n:]:
            mark = "✓" if rec.ok else "✗"
            items.append(f"{mark} {rec.time} {rec.cmd}")
        return "  ·  ".join(items)
