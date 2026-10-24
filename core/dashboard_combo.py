"""Small searchable dashboard selectors with actions outside the scroll area."""
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QVBoxLayout, QLineEdit,
                            QListWidget, QListWidgetItem)
from core.theme import THEME
from core.widgets import make_button


def show_panel(combo, panel, count, extra=100):
    t = THEME.tokens()
    panel.setStyleSheet(f"QFrame#DashboardPopup {{ background: {t['card']}; border: 1px solid {t['border_strong']}; border-radius: 8px; }} QLabel {{ color: {t['text2']}; }}")
    screen = combo.screen().availableGeometry()
    width = min(max(280, combo.width()), 460, screen.width())
    height = min(380, max(180, extra + min(count, 8) * 30), screen.height())
    point = combo.mapToGlobal(QPoint(0, combo.height()))
    x = min(max(point.x(), screen.left()), screen.right() - width + 1)
    y = point.y() if point.y() + height <= screen.bottom() else combo.mapToGlobal(QPoint(0, 0)).y() - height
    y = max(screen.top(), min(y, screen.bottom() - height + 1))
    panel.setGeometry(x, y, width, height)
    panel.show()


class DashboardCombo(QComboBox):
    all_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(1)
        self.popup = QFrame(self, Qt.WindowType.Popup)
        self.popup.setObjectName('DashboardPopup')
        box = QVBoxLayout(self.popup)
        box.setContentsMargins(10, 10, 10, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索选项')
        box.addWidget(self.search)
        self.all_button = make_button('全部')
        self.all_button.hide()
        self.all_button.clicked.connect(self.choose_all)
        box.addWidget(self.all_button)
        self.options = QListWidget()
        self.options.setUniformItemSizes(True)
        box.addWidget(self.options, 1)
        self.search.textChanged.connect(self.search_values)
        self.options.itemClicked.connect(self.choose)
        self.options.itemActivated.connect(self.choose)
        self.search.returnPressed.connect(self.choose_first)

    def set_all_action(self, label, callback):
        self.all_button.setText(label)
        self.all_button.show()
        self.all_requested.connect(callback)

    def showPopup(self):
        if not self.count():
            return
        self.options.clear()
        self.search.clear()
        for i in range(self.count()):
            item = QListWidgetItem(self.itemText(i))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.options.addItem(item)
        self.options.setCurrentRow(self.currentIndex())
        show_panel(self, self.popup, self.count())
        self.options.scrollToItem(self.options.currentItem())
        self.search.setFocus()

    def hidePopup(self):
        self.popup.hide()
        super().hidePopup()

    def choose(self, item):
        self.hidePopup()
        self.setCurrentIndex(item.data(Qt.ItemDataRole.UserRole))

    def choose_first(self):
        for i in range(self.options.count()):
            if not self.options.item(i).isHidden():
                self.choose(self.options.item(i))
                break

    def choose_all(self):
        self.hidePopup()
        self.all_requested.emit()

    def search_values(self, text):
        for i in range(self.options.count()):
            item = self.options.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def wheelEvent(self, event):
        # Scrolling the page must not change a closed filter and recalculate it.
        event.ignore()
