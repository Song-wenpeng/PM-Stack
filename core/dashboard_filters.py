"""Persistent dashboard attribute controls with a native combo appearance."""
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtWidgets import (QComboBox, QFrame, QVBoxLayout, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QLabel, QCheckBox)

from core.widgets import make_button
from core.theme import THEME


class AttributeCombo(QComboBox):
    selection_changed = pyqtSignal(list)

    def __init__(self, field, values, parent=None):
        super().__init__(parent)
        self.field = field
        self.values = list(values)
        self.selected = []
        self.setAccessibleName(field)
        self.setMinimumWidth(80)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(1)
        self.addItem('全部')
        self.popup = QFrame(self, Qt.WindowType.Popup)
        self.popup.setObjectName('AttributePopup')
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(10, 10, 10, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索' + field)
        layout.addWidget(self.search)
        self.select_all = QCheckBox('全选')
        self.select_all.setAccessibleName(field + '全选')
        self.select_all.clicked.connect(self.toggle_all)
        layout.addWidget(self.select_all)
        self.options = QListWidget()
        self.options.setAccessibleName(field + '可选值')
        for value in self.values:
            item = QListWidgetItem(str(value))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.options.addItem(item)
        layout.addWidget(self.options, 1)
        hint = QLabel('可多选；全选表示不限制此属性')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        actions = QHBoxLayout()
        self.all_button = make_button('全部 / 不限')
        self.all_button.clicked.connect(lambda: self.commit([]))
        actions.addWidget(self.all_button)
        actions.addStretch()
        self.apply_button = make_button('应用', 'primary')
        self.apply_button.clicked.connect(self.apply_selection)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self.search.textChanged.connect(self.search_values)
        self.options.itemChanged.connect(self.update_select_all)

    def set_selected(self, values):
        self.selected = [str(value) for value in values]
        label = '、'.join(self.selected) if self.selected else '全部'
        self.setItemText(0, label)
        self.setToolTip(self.field + '：' + label)

    def search_values(self, text):
        for i in range(self.options.count()):
            item = self.options.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def showPopup(self):
        t = THEME.tokens()
        self.popup.setStyleSheet(f"QFrame#AttributePopup {{ background: {t['card']}; border: 1px solid {t['border_strong']}; border-radius: 8px; }} QLabel {{ color: {t['text2']}; }} QListWidget::indicator:unchecked {{ border: 1px solid {t['text3']}; border-radius: 3px; background: {t['input']}; }}")
        self.search.clear()
        self.options.blockSignals(True)
        for i in range(self.options.count()):
            item = self.options.item(i)
            item.setCheckState(Qt.CheckState.Checked if not self.selected or item.text() in self.selected else Qt.CheckState.Unchecked)
        self.options.blockSignals(False)
        self.update_select_all()
        width = min(460, max(280, self.width()))
        height = min(400, max(300, 200 + self.options.count() * 30))
        screen = self.screen().availableGeometry()
        width = min(width, screen.width())
        height = min(height, screen.height())
        point = self.mapToGlobal(QPoint(0, self.height()))
        x = min(max(point.x(), screen.left()), screen.right() - width + 1)
        y = point.y() if point.y() + height <= screen.bottom() else self.mapToGlobal(QPoint(0, 0)).y() - height
        y = max(screen.top(), min(y, screen.bottom() - height + 1))
        self.popup.setGeometry(x, y, width, height)
        self.popup.show()
        self.search.setFocus()

    def hidePopup(self):
        self.popup.hide()
        super().hidePopup()

    def toggle_all(self, checked):
        self.options.blockSignals(True)
        for i in range(self.options.count()):
            self.options.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.options.blockSignals(False)
        self.update_select_all()

    def update_select_all(self, *_):
        count = sum(self.options.item(i).checkState() == Qt.CheckState.Checked for i in range(self.options.count()))
        self.select_all.blockSignals(True)
        self.select_all.setTristate(False)
        self.select_all.setChecked(count == self.options.count())
        if 0 < count < self.options.count():
            self.select_all.setCheckState(Qt.CheckState.PartiallyChecked)
        self.select_all.blockSignals(False)
        self.apply_button.setEnabled(count > 0)

    def apply_selection(self):
        selected = [self.options.item(i).text() for i in range(self.options.count())
                    if self.options.item(i).checkState() == Qt.CheckState.Checked]
        if selected:
            self.commit([] if len(selected) == self.options.count() else selected)

    def wheelEvent(self, event):
        event.ignore()

    def commit(self, values):
        self.hidePopup()
        self.set_selected(values)
        self.selection_changed.emit(self.selected.copy())
