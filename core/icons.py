# -*- coding: utf-8 -*-
"""极简线性图标库 — QPainter 手绘，无第三方依赖

所有图标基于 24x24 画布、1.8px 描边、圆角线帽，风格统一。
主题切换时按当前文字色重新绘制即可。
"""

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath


def _canvas(size):
    pix = QPixmap(size * 2, size * 2)  # 2x 保证高分屏清晰
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pix, p


def _pen(color, width=1.8):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


# ---- 各图标绘制函数（24x24 坐标系） ----

def _draw_chat(p):
    path = QPainterPath()
    path.addRoundedRect(QRectF(3.5, 4.5, 17, 12.5), 3.5, 3.5)
    path.moveTo(8, 17)
    path.lineTo(8, 21)
    path.lineTo(12.5, 17)
    p.drawPath(path)
    for x in (8.5, 12, 15.5):
        p.drawPoint(QPointF(x, 10.7))


def _draw_bars(p):
    p.drawLine(QPointF(4, 20), QPointF(20, 20))
    for x, h in ((7, 8), (12, 13), (17, 5)):
        p.drawLine(QPointF(x, 20), QPointF(x, 20 - h))


def _draw_trend(p):
    path = QPainterPath()
    path.moveTo(4, 17)
    path.lineTo(9.5, 11)
    path.lineTo(13.5, 14.5)
    path.lineTo(20, 7)
    p.drawPath(path)
    p.drawLine(QPointF(15.5, 7), QPointF(20, 7))
    p.drawLine(QPointF(20, 7), QPointF(20, 11.5))


def _draw_target(p):
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    p.drawPoint(QPointF(12, 12))


def _draw_cards(p):
    path = QPainterPath()
    path.addRoundedRect(QRectF(7.5, 3.5, 13, 14), 2.5, 2.5)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.addRoundedRect(QRectF(3.5, 6.5, 13, 14), 2.5, 2.5)
    p.fillPath(path2, QColor(0, 0, 0, 0))
    p.drawPath(path2)
    p.drawLine(QPointF(6.5, 11), QPointF(13.5, 11))
    p.drawLine(QPointF(6.5, 14.5), QPointF(13.5, 14.5))


def _draw_grid(p):
    for x, y in ((4.5, 4.5), (13.5, 4.5), (4.5, 13.5), (13.5, 13.5)):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, 6, 6), 1.6, 1.6)
        p.drawPath(path)


def _draw_settings(p):
    for y, knob in ((7, 15), (12, 9), (17, 14)):
        p.drawLine(QPointF(4, y), QPointF(20, y))
        p.drawEllipse(QPointF(knob, y), 1.8, 1.8)


def _draw_sun(p):
    p.drawEllipse(QPointF(12, 12), 4.5, 4.5)
    import math
    for i in range(8):
        a = math.pi / 4 * i
        x1 = 12 + 6.8 * math.cos(a)
        y1 = 12 + 6.8 * math.sin(a)
        x2 = 12 + 8.8 * math.cos(a)
        y2 = 12 + 8.8 * math.sin(a)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _draw_moon(p):
    path = QPainterPath()
    path.moveTo(14.5, 3.5)
    path.arcTo(3.5, 3.5, 17, 17, 90, -290)
    path.closeSubpath()
    # 简化为月牙：外弧 + 内弧
    outer = QPainterPath()
    outer.moveTo(15, 3.8)
    outer.arcTo(QRectF(4, 3.8, 16.4, 16.4), 78, -276)
    outer.arcTo(QRectF(8.2, 5.6, 12.8, 12.8), -128, 216)
    outer.closeSubpath()
    p.drawPath(outer)


def _draw_emoji_fallback(p, text):
    p.drawText(QRectF(0, 0, 24, 24), int(Qt.AlignmentFlag.AlignCenter), text)


_PAINTERS = {
    "chat": _draw_chat,
    "bars": _draw_bars,
    "trend": _draw_trend,
    "target": _draw_target,
    "cards": _draw_cards,
    "grid": _draw_grid,
    "settings": _draw_settings,
    "sun": _draw_sun,
    "moon": _draw_moon,
}

# 模块名 → 图标名
MODULE_ICONS = {
    "评论分析": "chat",
    "销量数据": "bars",
    "自适应图表": "trend",
    "市场规划": "target",
    "品类信息": "cards",
    "产品矩阵": "grid",
}


def get_icon(name, color, size=20):
    """按名称获取线性图标。

    Args:
        name: 图标名（chat/bars/trend/target/cards/settings/sun/moon），
              未知名称按文本回退绘制（用于插件模块的 emoji）
        color: 描边颜色
        size: 输出边长（逻辑像素）
    """
    pix, p = _canvas(size)
    scale = size / 24.0
    p.scale(scale, scale)
    painter_fn = _PAINTERS.get(name)
    if painter_fn:
        p.setPen(_pen(color))
        painter_fn(p)
    else:
        p.setPen(QColor(color))
        _draw_emoji_fallback(p, name)
    p.end()
    return QIcon(pix)


def get_module_icon(module_name, color, size=20, fallback_text=""):
    """获取模块图标，未知名称回退为 emoji/首字符。"""
    icon_name = MODULE_ICONS.get(module_name)
    if icon_name:
        return get_icon(icon_name, color, size)
    return get_icon(fallback_text or module_name[:1], color, size)
