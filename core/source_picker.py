"""Windows-native source pickers, reached through one browse menu."""
import os
from PyQt6.QtWidgets import QFileDialog


def browse_excel_source(parent=None, initial_path='', want_dir=False):
    initial = initial_path if os.path.isdir(initial_path) else os.path.dirname(initial_path)
    if want_dir:
        return QFileDialog.getExistingDirectory(parent, '选择待拆分文件夹', initial)
    path, _ = QFileDialog.getOpenFileName(parent, '选择待拆分 Excel', initial, 'Excel 文件 (*.xlsx *.xls)')
    return path
