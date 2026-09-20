"""UI for pairing the normal-browser extension and collecting one page."""
from pathlib import Path
import sys

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from core.widgets import make_button
from .extension_bridge import ExtensionBridge, default_browser


class ExtensionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("系统默认浏览器：" + default_browser()))
        instructions = QLabel("首次连接：在已登录 Amazon 的 Edge 配置中加载扩展，然后粘贴下方复制的连接码。")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        row = QHBoxLayout()
        for text, action in (("打开扩展文件夹", self.open_extension),
                             ("连接扩展 / 复制连接码", self.connect),
                             ("断开连接", self.disconnect)):
            button = make_button(text)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)
        self.connection = QLabel("尚未连接扩展")
        self.connection.setWordWrap(True)
        layout.addWidget(self.connection)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        QApplication.instance().aboutToQuit.connect(self.disconnect)

    def open_extension(self):
        root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        folder = root / "browser-extension"
        if not folder.exists():
            self.status.setText("未找到 browser-extension 文件夹，请将其放在 EXE 同一目录。")
            return
        import os
        os.startfile(str(folder))

    def connect(self):
        try:
            if not self.bridge:
                bridge = ExtensionBridge()
                bridge.start()
                self.bridge = bridge
            QApplication.clipboard().setText(self.bridge.token)
            self.status.setText("连接码已复制。在 Edge 的 PM Stack 扩展里粘贴，点击“保存并连接”。")
        except Exception as exc:
            self.status.setText("无法启动连接（请检查是否已有另一个 PM Stack 开启连接）：" + str(exc))

    def disconnect(self):
        if self.bridge:
            self.bridge.cancel()
            self.bridge.stop()
            self.bridge = None
        self.status.setText("已断开扩展连接")
        self.refresh()

    def refresh(self):
        if not self.bridge:
            self.connection.setText("尚未启动连接")
            return
        state = self.bridge.snapshot()
        self.connection.setText("扩展已连接" if state["connected"] else "等待扩展连接（在扩展里点击“立即检查任务”可刷新）")

