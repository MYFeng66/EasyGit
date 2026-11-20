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


# 常见 git 报错 → 大白话（需求文档 第八章「报错翻译」，随用随扩充）
ERROR_HINTS = [
    (
        "Please tell me who you are",
        "git 还不知道你是谁。点工具栏「打开终端」，运行："
        'git config --global user.name "你的名字" 、'
        'git config --global user.email "你的邮箱"，然后重试。',
    ),
    ("non-fast-forward", "远端有你没有的新提交，先拉取再推送。"),
    ("nothing to commit", "没有勾选任何改动，先在改动页勾文件。"),
]


def translate_error(output: str) -> str | None:
    """把 git 报错翻译成大白话；没见过的报错返回 None（界面显示原文第一行）"""
    for key, hint in ERROR_HINTS:
        if key in output:
            return hint
    return None
