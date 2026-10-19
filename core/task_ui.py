"""Shared task pages: reachable actions, field validation and result feedback."""
import os
import re
from functools import wraps
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox,
    QScrollArea, QFrame,
)

from core.widgets import ActionBar, LogConsole, make_button


def register_form(form):
    """Reserve an inline validation message beneath each form field."""
    for row in range(form.rowCount()):
        item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if item is None:
            continue
        label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        if label_item is None or label_item.widget() is None:
            continue
        taken = form.takeRow(row)
        container = QWidget()
        container.setObjectName('FieldGroup')
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        if taken.fieldItem.widget() is not None:
            layout.addWidget(taken.fieldItem.widget())
        elif taken.fieldItem.layout() is not None:
            layout.addLayout(taken.fieldItem.layout())
        hint = QLabel()
        hint.setObjectName('FieldError')
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setWordWrap(True)
        hint.hide()
        layout.addWidget(hint)
        label = taken.labelItem.widget()
        for field in container.findChildren(QWidget):
            if isinstance(field, (QLineEdit, QComboBox)):
                field._validation_hint = hint
                field._validation_label = label
                signal = field.textChanged if hasattr(field, 'textChanged') else field.currentTextChanged
                signal.connect(lambda _=None, f=field: clear_error(f))
        form.insertRow(row, label, container)


def clear_error(field):
    field.setProperty('validationError', False)
    field.style().unpolish(field)
    field.style().polish(field)
    hint = getattr(field, '_validation_hint', None)
    if hint is not None:
        hint.hide()


def mark_required(field):
    label = getattr(field, '_validation_label', None)
    if label is not None and '*' not in label.text():
        label.setText(label.text().rstrip(':：') + ' *:')


def validate_fields(pairs, button=None):
    missing = []
    for field, _ in pairs:
        clear_error(field)
    for field, name in pairs:
        mark_required(field)
        value = field.text() if hasattr(field, 'text') else field.currentText()
        if not value.strip():
            missing.append((field, name))
            field.setProperty('validationError', True)
            field.style().unpolish(field)
            field.style().polish(field)
            hint = getattr(field, '_validation_hint', None)
            if hint is not None:
                hint.setText('请填写' + name)
                hint.show()
    if not missing:
        return True
    first = missing[0][0]
    for field, _ in missing:
        toggle = getattr(field, '_advanced_toggle', None)
        if toggle is not None:
            toggle.setChecked(True)
    parent = first.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(first, 12, 48)
        parent = parent.parentWidget()
    first.setFocus(Qt.FocusReason.OtherFocusReason)
    bar = getattr(button, '_task_bar', None)
    if bar is not None:
        bar.summary.setText('请先填写：' + '、'.join(name for _, name in missing))
    return False


def validated(fields, button):
    """Validate direct method calls as well as button clicks."""
    def decorate(method):
        @wraps(method)
        def call(self):
            control = getattr(self, button)
            if not validate_fields(fields(self), control):
                log = getattr(control, '_task_log', None)
                bar = getattr(control, '_task_bar', None)
                if log is not None and bar is not None:
                    log.append('[提示] ' + bar.summary.text())
                return False
            return method(self)
        return call
    return decorate


class TaskBar(ActionBar):
    def __init__(self, hint='填写必填项后开始；结果会在这里显示。'):
        super().__init__()
        self.summary.setText(hint)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.result_path = ''
        self.folder_path = ''
        self.result_btn = make_button('打开结果', 'compact')
        self.folder_btn = make_button('打开文件夹', 'compact')
        self.result_btn.clicked.connect(lambda: self._open(self.result_path))
        self.folder_btn.clicked.connect(lambda: self._open(self.folder_path))
        for button in (self.result_btn, self.folder_btn):
            button.hide()
            self.row.addWidget(button)
        self._before = {}
        self._logged = []
        self.running = False

    def _open(self, path):
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
        else:
            self.summary.setText('结果文件已移动或删除，请检查保存位置。')

    @staticmethod
    def _stamp(path):
        try:
            stat = os.stat(path)
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def begin(self, candidates=(), folder=''):
        self.running = True
        self.result_path = ''
        self.folder_path = os.path.abspath(folder) if folder else ''
        self._before = {os.path.abspath(p): self._stamp(p) for p in candidates if p}
        self._logged = []
        self.result_btn.hide()
        self.folder_btn.hide()
        self.summary.setToolTip('')
        self.summary.setText('正在处理，请稍候…')

    def observe(self, text):
        if self.running:
            progress = re.search(r'(?:进度|已处理)[:：\s]*(\d+)\s*/\s*(\d+)', text)
            if progress:
                self.summary.setText(f'正在处理 · {progress[1]} / {progress[2]}')
        # Only completion messages may identify results; input paths in logs must
        # never become an "open result" link.
        if not self.running or not any(word in text for word in ('保存', '导出', '已输出', '→')):
            return
        if any(word in text for word in ('备份', '中间结果', 'checkpoint')):
            return
        for match in re.finditer(r'(?:[A-Za-z]:[\\/]|\\\\|/)[^\r\n<>"|]*?\.(?:xlsx|xls|png|jpg|jpeg|csv|html|pdf|txt)(?=[\s\'"）)]|$)', text, re.I):
            path = match.group().strip()
            if os.path.isfile(path):
                self._logged.append(os.path.abspath(path))
        # Several bundled scripts report relative output filenames.
        for tail in re.split(r'[：:]\s*|→\s*|保存(?:至|到)?\s*|输出到\s*', text)[1:]:
            path = tail.strip().strip("'\" ")
            if Path(path).suffix.lower() in ('.xlsx', '.xls', '.png', '.csv', '.html', '.pdf', '.txt') and os.path.isfile(path):
                self._logged.append(os.path.abspath(path))

    def finish(self, code, stopped=False):
        self.running = False
        if stopped:
            self.summary.setText('任务已停止；已处理的数据请查看日志及输出文件。')
        elif code != 0:
            self.summary.setText('处理失败，请展开运行日志查看原因后重试。')
        else:
            changed = [p for p, old in self._before.items()
                       if os.path.isfile(p) and self._stamp(p) != old]
            results = list(dict.fromkeys(changed + list(reversed(self._logged))))
            if results:
                self.result_path = results[0]
                self.folder_path = os.path.dirname(self.result_path)
                self.summary.setText('处理完成 · ' + os.path.basename(self.result_path))
                self.summary.setToolTip(self.result_path)
                self.result_btn.show()
            else:
                self.summary.setText('处理完成；详细结果见运行日志。')
        self.folder_btn.setVisible(bool(self.folder_path and os.path.isdir(self.folder_path)))


def pin_actions(page, *buttons, bar=None):
    """Move task controls out of a scrolling page into a stable action bar."""
    wrapper = QWidget()
    wrapper.setProperty('workspacePage', True)
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    layout.addWidget(scroll, 1)
    bar = bar or TaskBar()
    log = page.findChild(LogConsole)
    for button in buttons:
        button.setParent(bar)
        button.setFixedWidth(170 if button.property('buttonType') == 'primary' else 96)
        button._task_bar = bar
        button._task_log = log
        bar.row.addWidget(button)
    layout.addWidget(bar)
    wrapper.task_bar = bar
    return wrapper


def advanced_rows(form, first, last, title='高级设置'):
    """Fold optional form rows without discarding their values or field hints."""
    content = QWidget()
    content.setObjectName('AdvancedFields')
    inner = QFormLayout(content)
    inner.setContentsMargins(0, 4, 0, 4)
    inner.setSpacing(10)
    for _ in range(last - first + 1):
        row = form.takeRow(first)
        label = row.labelItem.widget() if row.labelItem else None
        field = row.fieldItem.widget()
        if field is None:
            field = row.fieldItem.layout()
        if label:
            inner.addRow(label, field)
        else:
            inner.addRow(field)
    toggle = make_button(title + ' · 展开', 'ghost')
    toggle.setCheckable(True)
    toggle.toggled.connect(content.setVisible)
    toggle.toggled.connect(lambda shown: toggle.setText(title + (' · 收起' if shown else ' · 展开')))
    form.insertRow(first, toggle)
    form.insertRow(first + 1, content)
    content.hide()
    # Validation can reveal a missing required field inside folded options.
    for field in content.findChildren(QWidget):
        if hasattr(field, '_validation_hint'):
            field._advanced_toggle = toggle
    return toggle
