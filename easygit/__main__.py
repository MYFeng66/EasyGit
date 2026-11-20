# -*- coding: utf-8 -*-
"""启动入口：python -m easygit（或双击 start_easygit.bat）。"""

from __future__ import annotations

import os
import sys


def main() -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    win = MainWindow()
    win.show()

    # 调试钩子：设 EASYGIT_SCREENSHOT=路径 时自动截图并退出（供自动化验证）
    shot = os.environ.get("EASYGIT_SCREENSHOT")
    if shot:
        def _grab():
            win.grab().save(shot)
            app.quit()
        QTimer.singleShot(800, _grab)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
