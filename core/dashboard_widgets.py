"""Native Qt dashboard charts, data table and workbook mapping dialog."""
import math
import csv
import io
import re
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt, QRectF, QPointF, QAbstractTableModel, QSortFilterProxyModel, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QKeySequence, QDesktopServices
from PyQt6.QtWidgets import (QWidget, QToolTip, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QToolButton, QFormLayout, QLineEdit, QDialogButtonBox, QScrollArea, QGroupBox,
    QTableView, QMenu, QApplication)

from core.dashboard_data import ALIASES, REQUIRED
from core.dashboard_import import detect_workbook, mapping_for
from core.theme import THEME


def number(value, percent=False):
    if pd.isna(value):
        return '—'
    return f'{value:.1%}' if percent else f'{value:,.2f}'.removesuffix('.00')


PRODUCT_URL_ROLE = Qt.ItemDataRole.UserRole + 1
AMAZON_DOMAINS = {'US': 'amazon.com', 'UK': 'amazon.co.uk', 'GB': 'amazon.co.uk',
                  'DE': 'amazon.de', 'FR': 'amazon.fr', 'IT': 'amazon.it', 'ES': 'amazon.es',
                  'CA': 'amazon.ca', 'JP': 'amazon.co.jp', 'AU': 'amazon.com.au'}


class DetailTable(QTableView):
    """Copy the displayed proxy cells and open product links without losing selection."""
    def copy_cell(self, index):
        if index.isValid():
            QApplication.clipboard().setText(str(index.data() or ''))

    def copy_selection(self, whole_rows=False):
        indexes = self.selectionModel().selectedIndexes()
        if not indexes:
            return
        rows = sorted({index.row() for index in indexes})
        columns = (range(self.model().columnCount()) if whole_rows
                   else sorted({index.column() for index in indexes}))
        selected = {(index.row(), index.column()) for index in indexes}
        output = io.StringIO(newline='')
        writer = csv.writer(output, delimiter='\t', lineterminator='\n')
        for row in rows:
            writer.writerow([str(self.model().index(row, col).data() or '')
                if whole_rows or (row, col) in selected else '' for col in columns])
        QApplication.clipboard().setText(output.getvalue().removesuffix('\n'))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        index = (self.currentIndex() if event.reason() == event.Reason.Keyboard
                 else self.indexAt(event.pos()))
        if index.isValid() and not self.selectionModel().isSelected(index):
            self.setCurrentIndex(index)
        menu = QMenu(self)
        cell = menu.addAction('复制单元格', lambda: self.copy_cell(index))
        cell.setEnabled(index.isValid())
        selection = menu.addAction('复制选中内容', lambda: self.copy_selection())
        selection.setEnabled(self.selectionModel().hasSelection())
        rows = menu.addAction('复制所选整行', lambda: self.copy_selection(whole_rows=True))
        rows.setEnabled(self.selectionModel().hasSelection())
        url = index.data(PRODUCT_URL_ROLE) if index.isValid() else None
        if url:
            menu.addSeparator()
            menu.addAction('打开亚马逊商品页', lambda: QDesktopServices.openUrl(QUrl(url)))
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mousePressEvent(self, event):
        self._press_position = event.position().toPoint()
        self._press_index = self.indexAt(self._press_position)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        index = self.indexAt(event.position().toPoint())
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and index.isValid() and index == getattr(self, '_press_index', None)
                and (event.position().toPoint() - self._press_position).manhattanLength() < QApplication.startDragDistance()):
            url = index.data(PRODUCT_URL_ROLE)
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        index = self.indexAt(event.position().toPoint())
        linked = index.isValid() and bool(index.data(PRODUCT_URL_ROLE))
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if linked else Qt.CursorShape.ArrowCursor)


class FrameModel(QAbstractTableModel):
    def __init__(self, frame=None, parent=None):
        super().__init__(parent)
        self.frame = frame if frame is not None else pd.DataFrame()
        self._columns = [self.frame[c].to_numpy() for c in self.frame]

    def replace(self, frame):
        self.beginResetModel()
        self.frame = frame.reset_index(drop=True)
        self._columns = [self.frame[c].to_numpy() for c in self.frame]
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.frame)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        val = self._columns[index.column()][index.row()]
        if self.frame.columns[index.column()] == 'ASIN' and role in (
                PRODUCT_URL_ROLE, Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.FontRole, Qt.ItemDataRole.ToolTipRole):
            site = str(self.frame.iloc[index.row()]['站点']).strip().upper() if '站点' in self.frame else ''
            domain = AMAZON_DOMAINS.get(site)
            if domain and re.fullmatch(r'[A-Z0-9]{10}', str(val)):
                url = f'https://www.{domain}/dp/{val}'
                if role == PRODUCT_URL_ROLE:
                    return url
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QColor(THEME.tokens()['accent'])
                if role == Qt.ItemDataRole.FontRole:
                    font = QFont()
                    font.setUnderline(True)
                    return font
                return f'点击打开亚马逊商品页：{url}\nCtrl+C或右键可复制；Ctrl/Shift点击用于多选。'
        if role == Qt.ItemDataRole.UserRole:
            return None if pd.isna(val) else val.item() if hasattr(val, 'item') else val
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return number(val) if isinstance(val, (int, float)) else '' if pd.isna(val) else str(val)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(val, (int, float)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return str(self.frame.columns[section]) if orientation == Qt.Orientation.Horizontal else str(section + 1)
        return None


class DetailProxy(QSortFilterProxyModel):
    """Filter a row mask once, instead of asking Qt to format every cell repeatedly."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_text = ''
        self.matches = None

    def setSourceModel(self, model):
        super().setSourceModel(model)
        model.modelReset.connect(self.rebuild_matches)

    def setFilterFixedString(self, text):
        if text == self.search_text:
            return
        self.search_text = text
        self.rebuild_matches()

    def rebuild_matches(self):
        frame = self.sourceModel().frame
        self.matches = None
        if self.search_text:
            text = self.search_text.casefold()
            mask = pd.Series(False, index=frame.index)
            for col in frame:
                # Preserve formatted numeric searching (e.g. 1,200) from DisplayRole.
                values = frame[col]
                if pd.api.types.is_numeric_dtype(values.dtype):
                    values = values.map(number)
                else:
                    values = values.fillna('').astype(str)
                mask |= values.str.casefold().str.contains(text, regex=False)
            self.matches = mask.to_numpy()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        # During modelReset Qt can consult the previous mask before our slot runs.
        return self.matches is None or row >= len(self.matches) or bool(self.matches[row])


def line_bounds(values, from_zero=False, percent=False):
    finite = [float(v) for v in values if pd.notna(v) and math.isfinite(v)]
    if not finite:
        return 0.0, 1.0
    low, high = min(finite), max(finite)
    if from_zero:
        return min(0.0, low), max(high, 0.01 if percent else 1.0)
    # At least 10% of the largest magnitude: do not magnify tiny changes.
    span = max(high - low, max(abs(low), abs(high)) * .1, .01 if percent else 1.0)
    padding = span * .12
    middle = (low + high) / 2
    lower, upper = middle - span / 2 - padding, middle + span / 2 + padding
    if low >= 0:
        lower = max(0.0, lower)
    return lower, upper


class Chart(QWidget):
    clicked = pyqtSignal(str)
    COLORS = ['#4D6BFE', '#23A68C', '#EA9A38', '#A16BE0', '#DD668C', '#6F8197']

    def __init__(self, title, kind='line', parent=None):
        super().__init__(parent)
        self.title, self.kind = title, kind
        self.labels, self.series, self.hits = [], [], []
        self.percent = False
        self.trend_controls = False
        self.zero_button = QToolButton(self)
        self.zero_button.setText('从零开始')
        self.zero_button.setCheckable(True)
        self.zero_button.setToolTip('开启后纵轴从零开始；关闭后按数据范围显示，并明确标注非零起点。')
        self.zero_button.toggled.connect(self.update)
        self.zoom_button = QToolButton(self)
        self.zoom_button.setText('放大查看')
        self.zoom_button.clicked.connect(self.open_expanded)
        self.zero_button.hide()
        self.zoom_button.hide()
        self.setMinimumSize(280, 300)
        self.setMouseTracking(True)
        THEME.changed.connect(self.update)

    def enable_trend_controls(self):
        self.trend_controls = True
        self.setMinimumHeight(480)
        self.zero_button.show()
        self.zoom_button.show()
        self.position_controls()

    def position_controls(self):
        self.zero_button.setGeometry(max(12, self.width() - 204), 40, 90, 28)
        self.zoom_button.setGeometry(max(110, self.width() - 106), 40, 90, 28)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_controls()

    def open_expanded(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.title + ' · 放大查看')
        box = QVBoxLayout(dialog)
        chart = Chart(self.title)
        chart.enable_trend_controls()
        chart.zoom_button.hide()
        chart.setMinimumSize(280, 240)
        chart.zero_button.setChecked(self.zero_button.isChecked())
        chart.set_data(self.labels, self.series, self.percent)
        def select_month(month):
            dialog.accept()
            self.clicked.emit(month)
        chart.clicked.connect(select_month)
        box.addWidget(chart)
        screen = self.screen().availableGeometry()
        dialog.resize(min(1280, screen.width() - 60), min(820, screen.height() - 60))
        dialog.exec()

    def set_data(self, labels, series, percent=False):
        self.labels, self.series, self.percent = list(labels), series, percent
        self.hits = []
        if self.kind == 'bar':
            self.setMinimumHeight(max(360, 70 + len(labels) * 24))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = THEME.tokens()
        p.setBrush(QColor(t['card']))
        p.setPen(QColor(t['border']))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        p.setPen(QColor(t['text']))
        p.drawText(QRectF(16, 12, self.width() - 32, 24), self.title)
        self.hits = []
        finite = [float(v) for _, vals in self.series for v in vals if pd.notna(v) and math.isfinite(v)]
        if not self.labels or not finite:
            p.setPen(QColor(t['text3']))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '暂无可计算数据')
            return
        maximum = max(max(finite), 0.01 if self.percent else 1)
        if self.kind == 'bar':
            left, right, top = 105, self.width() - 75, 48
            step = (self.height() - 68) / len(self.labels)
            for i, label in enumerate(self.labels):
                value = self.series[0][1][i]
                y = top + i * step
                p.setPen(QColor(t['text2']))
                shown = p.fontMetrics().elidedText(str(label), Qt.TextElideMode.ElideRight, 86)
                p.drawText(QRectF(12, y, 86, step), Qt.AlignmentFlag.AlignVCenter, shown)
                if pd.notna(value):
                    width = max(0, value / maximum * (right - left))
                    p.fillRect(QRectF(left, y + step * .2, width, step * .6), QColor(self.COLORS[0]))
                    p.drawText(QRectF(left + width + 5, y, 72, step), Qt.AlignmentFlag.AlignVCenter, number(value, self.percent))
                self.hits.append((QRectF(8, y, self.width() - 16, step), str(label), f'{label}：{number(value, self.percent)}'))
        else:
            # Wrap legends instead of truncating the plot when brand names are long.
            lower, upper = line_bounds(finite, not self.trend_controls or self.zero_button.isChecked(), self.percent)
            x, y = 16, 44
            if self.trend_controls:
                p.setPen(QColor(t['text2']))
                note = '纵轴从零开始' if self.zero_button.isChecked() else ('纵轴自适应 · 非零起点，请结合刻度比较' if lower != 0 else '纵轴自适应 · 起点为 0')
                p.drawText(QRectF(16, 76, self.width() - 32, 24), note)
                y = 104
            for i, (name, _) in enumerate(self.series):
                shown = p.fontMetrics().elidedText(str(name), Qt.TextElideMode.ElideRight, 115)
                if x + 145 > self.width():
                    x, y = 16, y + 20
                p.fillRect(QRectF(x, y + 5, 8, 8), QColor(self.COLORS[i % len(self.COLORS)]))
                p.setPen(QColor(t['text2']))
                p.drawText(QRectF(x + 14, y, 125, 20), shown)
                x += 145
            area = QRectF(70, y + 32, self.width() - 92, self.height() - y - 72)
            for tick in range(5):
                yy = area.bottom() - tick / 4 * area.height()
                p.setPen(QColor(t['border']))
                p.drawLine(QPointF(area.left(), yy), QPointF(area.right(), yy))
                p.setPen(QColor(t['text3']))
                value = lower + (upper - lower) * tick / 4
                label = number(value, True) if self.percent else (f'{value / 10000:.1f}万' if value >= 10000 else number(value))
                p.drawText(QRectF(4, yy - 10, 60, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            step = area.width() / max(1, len(self.labels) - 1)
            ticks = list(range(0, len(self.labels), max(1, math.ceil(len(self.labels) / max(2, area.width() / 95)))))
            if ticks[-1] != len(self.labels) - 1:
                if len(ticks) > 1 and (len(self.labels) - 1 - ticks[-1]) * step < 80:
                    ticks.pop()
                ticks.append(len(self.labels) - 1)
            for i, label in enumerate(self.labels):
                xx = area.left() + i * step if len(self.labels) > 1 else area.center().x()
                if i in ticks:
                    p.setPen(QColor(t['text3']))
                    p.drawText(QRectF(min(xx - 30, self.width() - 70), area.bottom() + 10, 65, 22), Qt.AlignmentFlag.AlignCenter, str(label))
                tooltip = '\n'.join([str(label)] + [f'{name}：{number(vals[i], self.percent)}' for name, vals in self.series])
                self.hits.append((QRectF(xx - max(step / 2, 10), area.top(), max(step, 20), area.height()), str(label), tooltip))
            for i, (_, values) in enumerate(self.series):
                path, active = QPainterPath(), False
                color = QColor(self.COLORS[i % len(self.COLORS)])
                p.setPen(QPen(color, 2))
                for j, value in enumerate(values):
                    if pd.isna(value) or not math.isfinite(value):
                        active = False
                        continue
                    xx = area.left() + j * step if len(self.labels) > 1 else area.center().x()
                    point = QPointF(xx, area.bottom() - (value - lower) / (upper - lower) * area.height())
                    if active:
                        path.lineTo(point)
                    else:
                        path.moveTo(point)
                    active = True
                    p.setBrush(color)
                    p.drawEllipse(point, 3, 3)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

    def mouseMoveEvent(self, event):
        for rect, _, tooltip in self.hits:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), tooltip, self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return
        QToolTip.hideText()
        self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for rect, label, _ in self.hits:
                if rect.contains(event.position()):
                    self.clicked.emit(label)
                    return


class ImportDialog(QDialog):
    def __init__(self, path, parent=None, detected=None):
        super().__init__(parent)
        self.path = path
        with pd.ExcelFile(path) as book:
            self.names = book.sheet_names
            self.detected = detected or detect_workbook(book)
        self.setWindowTitle('调整数据来源')
        self.resize(650, 680)
        layout = QVBoxLayout(self)
        label = QLabel(Path(path).name)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.mode = QComboBox()
        self.mode.addItems(['月度明细：每行 ASIN × 月份（BI 导出）', '历史工作簿：商品属性 + 月销量 + 月销额'])
        self.mode.setCurrentIndex(self.detected.get('mode', 1))
        self.mode.hide()
        summary = QLabel('自动关联：商品特征 + 历史销量 + 历史销额' if self.mode.currentIndex() else '已识别月度明细数据')
        summary.setWordWrap(True)
        layout.addWidget(summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.form = QFormLayout(content)
        self.sheet = QComboBox()
        self.sheet.addItems(self.names)
        self.sheet.setCurrentText(self.detected.get('sheet') or self.names[0])
        self.form.addRow('明细 / 属性表', self.sheet)
        self.history_box = QGroupBox('历史表（ASIN 列 + YYYY-MM 月份列）')
        history_form = QFormLayout(self.history_box)
        self.units, self.revenue = QComboBox(), QComboBox()
        for combo, keyword, title in [(self.units, '销量', '销量表'), (self.revenue, '销额', '销额表')]:
            combo.addItems(self.names)
            combo.setCurrentText(next((s for s in self.names if keyword in s), self.names[0]))
            history_form.addRow(title, combo)
        self.units.setCurrentText(self.detected.get('units') or self.units.currentText())
        self.revenue.setCurrentText(self.detected.get('revenue') or self.revenue.currentText())
        self.form.addRow(self.history_box)
        self.fields = {}
        for key in ALIASES:
            combo = QComboBox()
            self.fields[key] = combo
            self.form.addRow(key + (' *' if key in REQUIRED else ''), combo)
        self.site = QLineEdit()
        self.site.setPlaceholderText('未映射站点时填写，例如 US')
        self.currency = QLineEdit()
        self.currency.setPlaceholderText('未映射币种时填写，例如 USD')
        self.site.setText(self.detected.get('site', ''))
        self.currency.setText(self.detected.get('currency', ''))
        self.form.addRow('默认站点', self.site)
        self.form.addRow('默认币种', self.currency)
        hint = QLabel('商品特征通过 ASIN 关联历史记录，按所选月份统计。\n历史空白不补零，显示已有数据和覆盖率。\n重复商品属性的处理依据会保留在数据说明中。')
        hint.setWordWrap(True)
        self.form.addRow(hint)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用并生成看板')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.sheet.currentTextChanged.connect(self.populate)
        self.mode.currentIndexChanged.connect(self.populate)
        self.populate()
        for key, value in self.detected.get('mapping', {}).items():
            if key in self.fields and value:
                self.fields[key].setCurrentIndex(max(0, self.fields[key].findData(value)))

    def populate(self):
        try:
            columns = [str(c).strip() for c in pd.read_excel(self.path, sheet_name=self.sheet.currentText(), nrows=0).columns]
            for key, combo in self.fields.items():
                combo.clear()
                combo.addItem('不映射', '')
                for col in columns:
                    combo.addItem(col, col)
                alias = next((a for a in ALIASES[key] if a in columns), '')
                combo.setCurrentIndex(max(0, combo.findData(alias)))
                visible = self.mode.currentIndex() == 0 or key not in ('月份', *['销量', '销售额'])
                combo.setVisible(visible)
                self.form.labelForField(combo).setVisible(visible)
            self.history_box.setVisible(self.mode.currentIndex() == 1)
            self.error.clear()
        except Exception as exc:
            self.error.setText(str(exc))

    def options(self):
        return {'mode': self.mode.currentIndex(), 'sheet': self.sheet.currentText(),
                'units': self.units.currentText(), 'revenue': self.revenue.currentText(),
                'mapping': {k: c.currentData() or '' for k, c in self.fields.items()},
                'site': self.site.text().strip(), 'currency': self.currency.text().strip()}

    def validate(self):
        opts = self.options()
        required = REQUIRED if opts['mode'] == 0 else ['ASIN']
        if any(not opts['mapping'][key] for key in required):
            self.error.setText('请映射所有必填字段：' + '、'.join(required))
            return
        if any(not opts['mapping'][key] and not opts[default] for key, default in [('站点', 'site'), ('币种', 'currency')]):
            self.error.setText('请映射站点和币种，或填写对应的默认值，以明确统计口径。')
            return
        self.accept()
