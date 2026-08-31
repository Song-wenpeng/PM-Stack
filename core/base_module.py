# -*- coding: utf-8 -*-
"""模块基类 — 定义标准接口"""

from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget


class BaseModule(ABC):
    """所有功能模块的基类。

    子类必须:
      1. 定义 MODULE_INFO 字典（name, icon, order, description）
      2. 实现 create_widget() 返回 QWidget
    """

    @abstractmethod
    def create_widget(self, config_mgr, runner) -> QWidget:
        """创建并返回模块的面板 Widget。"""
