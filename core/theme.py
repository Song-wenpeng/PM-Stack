# -*- coding: utf-8 -*-
"""设计系统 — 明/暗双主题令牌、QSS 生成、全局主题管理

设计语言（参照现代 SaaS / DeepSeek 风格）：
- 大量留白、细分割线、克制的色彩：仅一个品牌蓝作为强调色
- 浅色：浅灰页面 + 白色卡片 + 1px 浅灰描边，12px 圆角
- 深色：分层深灰 + 同亮度描边，强调色自动提亮
- 三级文字层级：主文 / 次文 / 弱提示
"""

from PyQt6.QtCore import QObject, pyqtSignal
import os
import tempfile


# ============================================================
# 色板令牌
# ============================================================

LIGHT = {
    "name": "light",
    # 背景层级：页面 / 卡片与导航 / 输入框
    "bg": "#F7F8FA",
    "surface": "#FFFFFF",
    "card": "#FFFFFF",
    "input": "#FFFFFF",
    # 边框
    "border": "#E5E7EB",
    "border_strong": "#D1D5DB",
    # 品牌强调色（DeepSeek 蓝）
    "accent": "#4D6BFE",
    "accent_hover": "#3D5BEE",
    "accent_pressed": "#3451D1",
    "accent_dim": "rgba(77, 107, 254, 0.09)",
    "accent_border": "rgba(77, 107, 254, 0.35)",
    # 次按钮
    "secondary": "#FFFFFF",
    "secondary_hover": "#F3F4F6",
    # 语义色
    "danger": "#F54A45",
    "danger_dim": "rgba(245, 74, 69, 0.08)",
    "success": "#2BA471",
    "success_dim": "rgba(43, 164, 113, 0.10)",
    "warning": "#ED7B2F",
    "warning_dim": "rgba(237, 123, 47, 0.10)",
    # 文字
    "text": "#1F2329",
    "text2": "#646A73",
    "text3": "#8F959E",
    "text_on_accent": "#FFFFFF",
    # 下拉弹窗
    "popup_bg": "#FFFFFF",
    "popup_hover": "#F3F4F6",
    "popup_selected": "#4D6BFE",
    # 日志区
    "log_bg": "#FAFBFC",
    "selection": "rgba(77, 107, 254, 0.18)",
}

DARK = {
    "name": "dark",
    "bg": "#0E1013",
    "surface": "#14171C",
    "card": "#171B21",
    "input": "#10131A",
    "border": "#262B34",
    "border_strong": "#343A46",
    "accent": "#6B86FF",
    "accent_hover": "#8198FF",
    "accent_pressed": "#4D6BFE",
    "accent_dim": "rgba(107, 134, 255, 0.14)",
    "accent_border": "rgba(107, 134, 255, 0.40)",
    "secondary": "#1E232C",
    "secondary_hover": "#262C37",
    "danger": "#FF6B66",
    "danger_dim": "rgba(255, 107, 102, 0.12)",
    "success": "#3DC08B",
    "success_dim": "rgba(61, 192, 139, 0.12)",
    "warning": "#F0A35E",
    "warning_dim": "rgba(240, 163, 94, 0.12)",
    "text": "#E8EAED",
    "text2": "#9BA1AB",
    "text3": "#5F6672",
    "text_on_accent": "#FFFFFF",
    "popup_bg": "#1A1F27",
    "popup_hover": "#242B36",
    "popup_selected": "#4D6BFE",
    "log_bg": "#0B0D11",
    "selection": "rgba(107, 134, 255, 0.28)",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# 圆角 / 间距常量（供组件代码引用）
RADIUS_CARD = 12
RADIUS_CTRL = 8
FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif'
MONO_FAMILY = 'Consolas, "Cascadia Mono", "Courier New", monospace'


# ============================================================
# 主题管理器（全局单例）
# ============================================================

class ThemeManager(QObject):
    """管理当前主题，切换时发出 changed 信号并生成新 QSS。"""

    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._name = "light"

    @property
    def name(self):
        return self._name

    @property
    def is_dark(self):
        return self._name == "dark"

    def tokens(self):
        return PALETTES[self._name]

    def set_theme(self, name):
        if name not in PALETTES or name == self._name:
            return
        self._name = name
        self.changed.emit(name)

    def toggle(self):
        self.set_theme("dark" if self._name == "light" else "light")

    def qss(self):
        return build_qss(self.tokens())


THEME = ThemeManager()


# ============================================================
# QSS 生成
# ============================================================

def _ensure_check_icons(accent: str, box_bg: str) -> str:
    """生成勾选图标 PNG（圆角框 + 强调色√），返回文件路径供 QSS 引用。"""
    from PyQt6.QtGui import QImage, QPainter, QPen, QColor
    from PyQt6.QtCore import Qt, QPointF

    cache_dir = os.path.join(tempfile.gettempdir(), "pm_stack_theme")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(
        cache_dir, f"check_{accent.lstrip('#')}_{box_bg.lstrip('#')}.png")
    if os.path.exists(path):
        return path

    size = 32  # 2x 超采样，抗锯齿更平滑
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # 圆角底 + 强调色描边
    p.setPen(QPen(QColor(accent), 2.5))
    p.setBrush(QColor(box_bg))
    p.drawRoundedRect(2, 2, size - 4, size - 4, 7, 7)
    # 勾选符号
    p.setPen(QPen(QColor(accent), 3.5, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    from PyQt6.QtGui import QPainterPath
    path_obj = QPainterPath()
    path_obj.moveTo(QPointF(9, 17))
    path_obj.lineTo(QPointF(14, 22))
    path_obj.lineTo(QPointF(23, 11))
    p.drawPath(path_obj)
    p.end()
    img.save(path, "PNG")
    return path


def build_qss(t):
    check_icon = _ensure_check_icons(t["accent"], t["input"]).replace("\\", "/")
    return f"""
/* ===== 全局 ===== */
QWidget {{
    background-color: {t['bg']};
    color: {t['text']};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {t['bg']}; }}
QLabel {{
    background-color: transparent;
    color: {t['text']};
}}

/* ===== 导航栏（左侧窄图标栏） ===== */
QWidget#NavRail {{
    background-color: {t['surface']};
    border-right: 1px solid {t['border']};
}}
QLabel#NavBrand {{
    background-color: {t['accent_dim']};
    color: {t['accent']};
    border-radius: 10px;
    font-size: 18px;
    font-weight: 800;
}}
QToolButton#NavItem {{
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 6px;
}}
QToolButton#NavItem:hover {{ background-color: {t['secondary_hover']}; }}
QToolButton#NavItem:checked {{ background-color: {t['accent_dim']}; }}
QToolButton#NavUtility {{
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 6px;
}}
QToolButton#NavUtility:hover {{ background-color: {t['secondary_hover']}; }}
QFrame#NavSeparator {{
    background-color: {t['border']};
    max-height: 1px;
    border: none;
}}

/* ===== 顶部标题栏 ===== */
QWidget#Header {{
    background-color: transparent;
    border-bottom: 1px solid {t['border']};
}}
QLabel#PageTitle {{
    color: {t['text']};
    font-size: 20px;
    font-weight: 700;
}}
QLabel#PageSubtitle {{
    color: {t['text2']};
    font-size: 12px;
}}
QLabel#ApiBadge {{
    background-color: {t['warning_dim']};
    color: {t['warning']};
    border: none;
    border-radius: 11px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#ApiBadge[configured="true"] {{
    background-color: {t['success_dim']};
    color: {t['success']};
}}

/* ===== 卡片 ===== */
QFrame#Card {{
    background-color: {t['card']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#CardTitle {{
    color: {t['text']};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#CardSubtitle {{
    color: {t['text3']};
    font-size: 12px;
}}
QLabel#CardHintIcon {{
    color: {t['text3']};
    font-size: 12px;
}}

/* ===== 按钮 ===== */
QPushButton {{
    background-color: {t['secondary']};
    color: {t['text']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS_CTRL}px;
    padding: 7px 16px;
    font-size: 13px;
    min-height: 20px;
}}
QPushButton:hover {{ background-color: {t['secondary_hover']}; }}
QPushButton:pressed {{ background-color: {t['border']}; }}
QPushButton:disabled {{
    color: {t['text3']};
    background-color: {t['secondary_hover']};
    border-color: {t['border']};
}}
QPushButton[buttonType="primary"] {{
    background-color: {t['accent']};
    color: {t['text_on_accent']};
    border: none;
    font-weight: 600;
    padding: 8px 22px;
}}
QPushButton[buttonType="primary"]:hover {{ background-color: {t['accent_hover']}; }}
QPushButton[buttonType="primary"]:pressed {{ background-color: {t['accent_pressed']}; }}
QPushButton[buttonType="primary"]:disabled {{
    background-color: {t['accent_dim']};
    color: {t['text3']};
}}
QPushButton[buttonType="danger"] {{
    background-color: transparent;
    color: {t['danger']};
    border: 1px solid {t['danger']};
}}
QPushButton[buttonType="danger"]:hover {{ background-color: {t['danger_dim']}; }}
QPushButton[buttonType="danger"]:disabled {{
    color: {t['text3']};
    border-color: {t['border']};
    background-color: transparent;
}}
QPushButton[buttonType="ghost"] {{
    background-color: transparent;
    border: none;
    color: {t['text2']};
    padding: 5px 10px;
}}
QPushButton[buttonType="ghost"]:hover {{
    background-color: {t['secondary_hover']};
    color: {t['text']};
}}
QPushButton[buttonType="compact"] {{
    padding: 4px 12px;
    font-size: 12px;
    min-height: 16px;
}}

/* ===== 输入框 / 下拉 / 数字框 ===== */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {t['input']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CTRL}px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: {t['selection']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {t['border_strong']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t['accent']};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {t['secondary_hover']};
    color: {t['text3']};
}}
QLineEdit::placeholder {{ color: {t['text3']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {t['text3']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['popup_bg']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {t['popup_selected']};
    selection-color: #FFFFFF;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 20px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {t['text2']};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {t['text2']};
}}

/* ===== Tab（分段式） ===== */
QTabWidget::pane {{
    border: none;
    background-color: transparent;
    padding-top: 12px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {t['text2']};
    padding: 8px 16px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {t['accent']};
    font-weight: 600;
    border-bottom: 2px solid {t['accent']};
}}
QTabBar::tab:hover:!selected {{ color: {t['text']}; }}

/* ===== 日志控制台 ===== */
QFrame#LogConsole {{
    background-color: {t['log_bg']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#LogTitle {{
    color: {t['text2']};
    font-size: 12px;
    font-weight: 600;
}}
QLabel#LogDot {{ border-radius: 4px; }}
QTextEdit, QPlainTextEdit {{
    background-color: {t['log_bg']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CTRL}px;
    font-family: {MONO_FAMILY};
    font-size: 12px;
    padding: 8px;
    selection-background-color: {t['selection']};
}}
QTextEdit#LogBody, QPlainTextEdit#LogBody {{ border: none; background-color: transparent; }}

/* ===== 表格 ===== */
QTableWidget {{
    background-color: {t['card']};
    alternate-background-color: {t['log_bg']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CTRL}px;
    gridline-color: {t['border']};
    selection-background-color: {t['accent_dim']};
    selection-color: {t['text']};
}}
QTableWidget::item {{ padding: 4px 6px; border: none; }}
QHeaderView::section {{
    background-color: {t['log_bg']};
    color: {t['text2']};
    border: none;
    border-bottom: 1px solid {t['border']};
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {t['log_bg']};
    border: none;
    border-bottom: 1px solid {t['border']};
}}

/* ===== 列表 ===== */
QListWidget {{
    background-color: {t['card']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CTRL}px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin: 2px 4px;
}}
QListWidget::item:selected {{
    background-color: {t['accent_dim']};
    color: {t['accent']};
}}
QListWidget::item:hover:!selected {{ background-color: {t['secondary_hover']}; }}

/* ===== 复选框 ===== */
QCheckBox {{ color: {t['text']}; spacing: 6px; background-color: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {t['border_strong']};
    border-radius: 4px;
    background-color: {t['input']};
}}
QCheckBox::indicator:checked {{
    image: url({check_icon});
    border: none;
    background-color: transparent;
}}

/* ===== 提示文字 ===== */
QLabel#FormHint {{ color: {t['text3']}; font-size: 12px; background: transparent; }}
QLabel#ErrorText {{ color: {t['danger']}; font-size: 12px; background: transparent; }}

/* ===== 状态栏 ===== */
QStatusBar {{
    background-color: {t['surface']};
    color: {t['text3']};
    border-top: 1px solid {t['border']};
    font-size: 11px;
}}

/* ===== Tooltip ===== */
QToolTip {{
    background-color: {t['card']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ===== 滚动条（纤细） ===== */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t['border_strong']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['text3']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none; height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border_strong']};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t['text3']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none; width: 0;
}}

/* ===== 分割器 / 滚动区 ===== */
QSplitter::handle {{ background-color: transparent; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QScrollArea {{ background-color: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background-color: transparent; }}

/* ===== 分组框（兼容旧代码，视觉等同卡片） ===== */
QGroupBox {{
    background-color: {t['card']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px;
    margin-top: 18px;
    padding: 18px 14px 14px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {t['text']};
    font-size: 14px;
}}
"""
