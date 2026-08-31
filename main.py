# -*- coding: utf-8 -*-
"""PM Stack V1.10.2 — 内置评论分析并发测试子模块"""

import sys
import os

# Qt 高 DPI 适配（必须在 QApplication 创建之前设置）
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
# 防止中文用户名路径导致 matplotlib 缓存崩溃
os.environ['MPLCONFIGDIR'] = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'mpl_config')

# 确保 APP 目录在 sys.path 中
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from core.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    # 主题 QSS 由 MainWindow 按配置应用（明/暗双主题）
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
