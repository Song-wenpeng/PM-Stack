# -*- coding: utf-8 -*-
"""共享 UI 组件库 — 现代风格的统一构件

组件:
- Card            : 白色/深色卡片容器（标题 + 副标题 + 内容区）
- PageHeader      : 页面标题栏（标题 + 副标题 + 右侧操作位）
- LogConsole      : 运行日志控制台（状态点 + 清空 + 等宽日志体）
- FileDropLineEdit: 支持拖拽文件/文件夹的路径输入框
- make_button     : 按角色创建按钮（primary/secondary/danger/ghost/compact）
- configure_combo : 主题感知的深色/浅色下拉框统一配置
- set_running_state: 执行按钮运行态切换
- browse_* / file_row / make_hint_label / require_fields / default_output
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout, QFileDialog,
    QTextEdit, QLabel, QFrame, QWidget, QComboBox, QStyledItemDelegate,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette

from .theme import THEME, MONO_FAMILY


# ============================================================
# 按钮
# ============================================================

def make_button(text, role="secondary", tooltip=""):
    """按语义角色创建按钮：primary / secondary / danger / ghost / compact。"""
    btn = QPushButton(text)
    if role and role != "secondary":
        btn.setProperty("buttonType", role)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def set_running_state(btn, running, idle_text=None, running_text="⏳ 运行中..."):
    """切换执行按钮的运行状态（自动记忆/恢复原始文案）。"""
    if running:
        if idle_text is None:
            idle_text = btn.text()
        btn.setProperty("_idleText", idle_text)
        btn.setEnabled(False)
        btn.setText(running_text)
    else:
        btn.setEnabled(True)
        saved = btn.property("_idleText")
        btn.setText(saved if saved else (idle_text or btn.text()))


# ============================================================
# 卡片
# ============================================================

class Card(QFrame):
    """卡片容器：可选标题/副标题，内容加入 content_layout。

    用法:
        card = Card("单文件销量拆分", "按 ASIN/子体拆分销量数据")
        form = QFormLayout()
        ...
        card.content_layout.addLayout(form)
        page_layout.addWidget(card)
    """

    def __init__(self, title="", subtitle="", hint="", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        if title:
            header_row = QHBoxLayout()
            header_row.setSpacing(6)
            title_lbl = QLabel(title)
            title_lbl.setObjectName("CardTitle")
            header_row.addWidget(title_lbl)
            if hint:
                mark = QLabel("ⓘ")
                mark.setObjectName("CardHintIcon")
                mark.setToolTip(hint)
                header_row.addWidget(mark)
            header_row.addStretch()
            layout.addLayout(header_row)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("CardSubtitle")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        if title or subtitle:
            layout.addSpacing(2)

        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        layout.addLayout(self.content_layout)


# ============================================================
# 日志控制台
# ============================================================

_STATUS_COLORS = {
    "idle": "text3",
    "running": "accent",
    "ok": "success",
    "error": "danger",
}


class LogConsole(QFrame):
    """运行日志控制台：头部状态点 + 标题 + 清空按钮，下方等宽日志体。"""

    def __init__(self, max_height=200, parent=None):
        super().__init__(parent)
        self.setObjectName("LogConsole")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._dot = QLabel()
        self._dot.setObjectName("LogDot")
        self._dot.setFixedSize(8, 8)
        header.addWidget(self._dot)
        title = QLabel("运行日志")
        title.setObjectName("LogTitle")
        header.addWidget(title)
        header.addStretch()
        clear_btn = make_button("清空", "ghost", "清空日志内容")
        clear_btn.clicked.connect(self.clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.text = QTextEdit()
        self.text.setObjectName("LogBody")
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 10))
        self.text.setPlaceholderText("任务输出将在这里显示…")
        layout.addWidget(self.text)

        self.setMaximumHeight(max_height)
        self.set_status("idle")

    # ---- 对外接口 ----

    def log(self, msg):
        self.text.append(msg)
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    append = log  # 兼容 runner.log_signal.connect(console.append)

    def clear(self):
        self.text.clear()
        self.set_status("idle")

    def setPlainText(self, msg):  # 兼容旧调用
        self.text.setPlainText(msg)

    def set_status(self, status):
        t = THEME.tokens()
        color = t[_STATUS_COLORS.get(status, "text3")]
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;")


# ============================================================
# 下拉框（主题感知）
# ============================================================

def configure_combo(combo, max_visible=8):
    """统一配置 QComboBox：主题化弹窗、最多显示行数、统一绘制。

    委托绘制时实时读取当前主题令牌，主题切换后无需重建。
    """
    class _ComboDelegate(QStyledItemDelegate):
        def paint(self, painter, option, index):
            from PyQt6.QtWidgets import QStyle
            t = THEME.tokens()
            st = option.state
            selected = bool(st & QStyle.StateFlag.State_Selected)
            bg = QColor(t["popup_selected"]) if selected else QColor(t["popup_bg"])
            if not selected and (st & QStyle.StateFlag.State_MouseOver):
                bg = QColor(t["popup_hover"])
            fg = QColor("#FFFFFF") if selected else QColor(t["text"])
            painter.save()
            painter.fillRect(option.rect, bg)
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                painter.setPen(fg)
                painter.drawText(
                    option.rect.adjusted(10, 0, -6, 0),
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                    str(text),
                )
            painter.restore()

        def sizeHint(self, option, index):
            s = super().sizeHint(option, index)
            s.setHeight(32)
            return s

    combo.setMaxVisibleItems(max_visible)
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    view = combo.view()
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setMouseTracking(True)
    view.setItemDelegate(_ComboDelegate(view))
    pal = view.palette()
    t = THEME.tokens()
    pal.setColor(QPalette.ColorRole.Base, QColor(t["popup_bg"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t["popup_selected"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    view.setPalette(pal)
    return combo


# ============================================================
# 路径输入
# ============================================================

class FileDropLineEdit(QLineEdit):
    """支持拖拽文件/文件夹路径的 QLineEdit。

    从资源管理器拖入文件即可自动填入路径，也可正常手动输入。
    拖入后发射 path_dropped(str) 信号，便于模块自动联动。
    """

    path_dropped = pyqtSignal(str)

    def __init__(self, parent=None, want_dir=False, placeholder=""):
        super().__init__(parent)
        self._want_dir = want_dir
        self.setAcceptDrops(True)
        if placeholder:
            self.setPlaceholderText(placeholder)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if not path:
            return
        if self._want_dir and os.path.isfile(path):
            path = os.path.dirname(path)
        self.setText(path)
        self.path_dropped.emit(path)
        event.acceptProposedAction()


def browse_file(line_edit, parent=None, caption="选择文件",
                filter_str="Excel (*.xlsx *.xls)"):
    path, _ = QFileDialog.getOpenFileName(parent, caption, "", filter_str)
    if path:
        line_edit.setText(path)
    return path


def browse_save_file(line_edit, parent=None, caption="选择输出文件",
                     filter_str="Excel (*.xlsx)"):
    path, _ = QFileDialog.getSaveFileName(parent, caption, "", filter_str)
    if path:
        line_edit.setText(path)
    return path


def browse_dir(line_edit, parent=None, caption="选择文件夹"):
    path = QFileDialog.getExistingDirectory(parent, caption)
    if path:
        line_edit.setText(path)
    return path


def file_row(line_edit, mode="open", caption="选择文件",
             filter_str="Excel (*.xlsx *.xls)", parent=None):
    """构建「路径输入框 + 浏览按钮」标准行。"""
    btn = make_button("浏览")
    if mode == "open":
        btn.clicked.connect(
            lambda: browse_file(line_edit, parent, caption, filter_str))
    elif mode == "save":
        btn.clicked.connect(
            lambda: browse_save_file(line_edit, parent, caption, filter_str))
    else:
        btn.clicked.connect(lambda: browse_dir(line_edit, parent, caption))
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(line_edit)
    row.addWidget(btn)
    return row


# ============================================================
# 表单小工具
# ============================================================

def make_hint_label(text):
    """表单内的小号弱提示文字。"""
    lbl = QLabel(text)
    lbl.setObjectName("FormHint")
    lbl.setWordWrap(True)
    return lbl


def require_fields(log_area, *pairs):
    """必填校验：任一字段为空时向日志区输出提示并返回 False。"""
    missing = [name for value, name in pairs if not (value or "").strip()]
    if missing:
        log_area.append(
            "[提示] 请先填写: " + "、".join("「" + m + "」" for m in missing))
        return False
    return True


def default_output(input_path, suffix):
    """根据输入路径生成默认输出路径：同名加后缀。"""
    path = Path(str(input_path).strip().strip('"').strip("'"))
    if path.suffix:
        return str(path.with_name(f"{path.stem}{suffix}{path.suffix}"))
    return f"{input_path}{suffix}.xlsx"
