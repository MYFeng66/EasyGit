# -*- coding: utf-8 -*-
"""个人配置（数据与代码分离，需求文档 第二章 机制 4）。
存放位置：%USERPROFILE%\\.easygit\\settings.json
预留字段 acknowledged_untracked：状态面板「已退库·已知晓」清单。"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_DIR = Path.home() / ".easygit"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {"repos": [], "acknowledged_untracked": []}


def load() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    # 兼容旧版本：缺的字段补默认值
    for key, value in DEFAULTS.items():
        data.setdefault(key, value)
    return data


def save(data: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
