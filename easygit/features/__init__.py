# -*- coding: utf-8 -*-
"""功能注册表（需求文档 第二章 机制 1：功能 = 模块）。
加功能 = 新建包 + 一行 import；删功能 = 去掉那一行 import。"""

from __future__ import annotations

FEATURES: list[dict] = []


def register(create_page, title: str, order: int = 100) -> None:
    """每个功能模块导入时调用本函数完成注册。
    create_page(ctx) -> QWidget；order 越小排位越靠前。"""
    FEATURES.append({"title": title, "order": order, "create": create_page})
    FEATURES.sort(key=lambda f: f["order"])


def _import_builtin_features() -> None:
    # 每个功能一行 import 即入列；删功能 = 删掉对应行
    from . import status_page    # noqa: F401  「改动」页
    from . import history_page   # noqa: F401  「历史」页


_import_builtin_features()
