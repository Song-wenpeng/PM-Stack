"""Inline category/template editor. Changes remain drafts until saved."""
import json
import os
from uuid import uuid4
import tempfile
from copy import deepcopy

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                            QLineEdit, QPlainTextEdit, QListWidget, QComboBox,
                            QCheckBox, QLabel, QMessageBox, QScrollArea)
from core.widgets import make_button
from core.field_workbook import LOG_FIELDS


class FieldTemplatePanel(QWidget):
    saved = pyqtSignal(str)

    def __init__(self, config_path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.dirty = False
        self.loading = False
        self.rows = []
        self.current = -1
        self.original_key = None
        self.product = {}
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('类目与字段模板'))
        hint = QLabel('左侧勾选本次提取字段；这里编辑类目模板。\n仅规范语言和格式，结果仍需人工验证。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        self.name = QLineEdit()
        self.name.setPlaceholderText('例如：金属外壳排插')
        self.copy_from = QComboBox()
        form.addRow('类目名称', self.name)
        form.addRow('复制字段自', self.copy_from)
        self.list = QListWidget()
        self.list.setMaximumHeight(160)
        form.addRow(self.list)
        actions = QHBoxLayout()
        for label, callback in [('+ 字段', self.add_field), ('删除', self.remove_field),
                                ('上移', lambda: self.move_field(-1)), ('下移', lambda: self.move_field(1))]:
            button = make_button(label, 'compact')
            button.clicked.connect(callback)
            actions.addWidget(button)
        form.addRow(actions)
        self.field_name = QLineEdit()
        self.rule = QPlainTextEdit()
        self.rule.setMaximumHeight(95)
        self.language = QLineEdit()
        self.language.setPlaceholderText('如：简体中文；留空沿用原规则')
        self.format = QPlainTextEdit()
        self.format.setMaximumHeight(85)
        self.format.setPlaceholderText('如：颜色用中文，多色以“；”分隔，不输出其他规格')
        self.vision = QCheckBox('允许图片补充识别')
        self.vision_rule = QPlainTextEdit()
        self.vision_rule.setMaximumHeight(85)
        for label, widget in [('字段名称', self.field_name), ('提取说明', self.rule),
                              ('输出语言', self.language), ('格式与示例', self.format),
                              ('', self.vision), ('图片提取说明', self.vision_rule)]:
            form.addRow(label, widget)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        footer = QHBoxLayout()
        for label, callback in [('保存', self.save), ('取消', self.cancel)]:
            button = make_button(label, 'primary' if label == '保存' else 'compact')
            button.clicked.connect(callback)
            footer.addWidget(button)
        layout.addLayout(footer)
        self.list.currentRowChanged.connect(self.select_field)
        self.copy_from.currentIndexChanged.connect(self.copy_fields)
        for widget in (self.name, self.field_name, self.language):
            widget.textChanged.connect(self.changed)
        for widget in (self.rule, self.format, self.vision_rule):
            widget.textChanged.connect(self.changed)
        self.vision.toggled.connect(self.changed)
        self.hide()

    def changed(self, *_):
        if not self.loading:
            self.dirty = True
            if 0 <= self.current < self.list.count():
                self.list.item(self.current).setText(self.field_name.text() or '未命名字段')

    def can_discard(self):
        return not self.dirty or QMessageBox.question(
            self, '未保存的模板', '放弃未保存的修改？',
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def read_config(self):
        with open(self.config_path, encoding='utf-8') as file:
            return json.load(file)

    def open_product(self, key=None):
        if not self.can_discard():
            return False
        try:
            self.products = self.read_config().get('products', {})
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '无法读取模板', str(exc))
            return False
        self.original_key = key
        self.product = deepcopy(self.products.get(key, {}))
        self.loading = True
        self.name.setText(self.product.get('name', ''))
        self.copy_from.clear()
        self.copy_from.addItem('不复制', None)
        for k, product in self.products.items():
            self.copy_from.addItem(product.get('name', k), k)
        self.copy_from.setEnabled(key is None)
        self.load_fields(self.product)
        self.loading = False
        self.dirty = False
        self.show()
        return True

    def load_fields(self, product):
        self.current = -1
        self.rows = []
        self.list.clear()
        for field in product.get('target_fields', []):
            output = product.get('field_output', {}).get(field, {})
            self.rows.append(dict(name=field, rule=product.get('field_config', {}).get(field, ''),
                                  language=output.get('language', ''), format=output.get('format', ''),
                                  vision=field in product.get('vision_allowed_fields', []),
                                  vision_rule=product.get('vision_field_config', {}).get(field, '')))
            self.list.addItem(field)
        self.list.setCurrentRow(0 if self.rows else -1)
        if not self.rows:
            self.select_field(-1)

    def store_field(self):
        if 0 <= self.current < len(self.rows):
            self.rows[self.current] = dict(name=self.field_name.text().strip(), rule=self.rule.toPlainText().strip(),
                language=self.language.text().strip(), format=self.format.toPlainText().strip(),
                vision=self.vision.isChecked(), vision_rule=self.vision_rule.toPlainText().strip())

    def select_field(self, index):
        self.store_field()
        self.current = index
        row = self.rows[index] if 0 <= index < len(self.rows) else {}
        previous = self.loading
        self.loading = True
        for widget, value in [(self.field_name, row.get('name', '')), (self.language, row.get('language', ''))]:
            widget.setText(value)
        for widget, value in [(self.rule, row.get('rule', '')), (self.format, row.get('format', '')),
                              (self.vision_rule, row.get('vision_rule', ''))]:
            widget.setPlainText(value)
        self.vision.setChecked(row.get('vision', False))
        for widget in (self.field_name, self.language, self.rule, self.format, self.vision, self.vision_rule):
            widget.setEnabled(index >= 0)
        self.loading = previous

    def copy_fields(self):
        if self.loading:
            return
        if self.rows and not self.can_discard():
            return
        self.loading = True
        self.load_fields(self.products.get(self.copy_from.currentData(), {}))
        self.loading = False
        self.dirty = True

    def add_field(self):
        self.store_field()
        self.rows.append({})
        self.list.addItem('未命名字段')
        self.list.setCurrentRow(len(self.rows) - 1)
        self.dirty = True
        self.field_name.setFocus()

    def rebuild(self, index):
        self.current = -1
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([r.get('name') or '未命名字段' for r in self.rows])
        self.list.blockSignals(False)
        self.list.setCurrentRow(index)
        if index < 0:
            self.select_field(-1)
        self.dirty = True

    def remove_field(self):
        index = self.current
        if index >= 0:
            self.rows.pop(index)
            self.rebuild(min(index, len(self.rows) - 1))

    def move_field(self, delta):
        index = self.current
        if 0 <= index + delta < len(self.rows) and index >= 0:
            self.store_field()
            self.rows[index], self.rows[index + delta] = self.rows[index + delta], self.rows[index]
            self.rebuild(index + delta)

    def save(self):
        self.store_field()
        key, name = self.original_key, self.name.text().strip()
        names = [r.get('name', '') for r in self.rows]
        if not name:
            QMessageBox.warning(self, '请检查类目', '请填写类目名称。')
            return
        if not names or any(not n or ',' in n or n.upper() == 'ASIN' or n in LOG_FIELDS for n in names) or len(set(names)) != len(names):
            QMessageBox.warning(self, '请检查字段', '至少添加一个字段；字段名不能空白、重复、包含英文逗号或使用 ASIN、过程日志列名。')
            return
        pending = None
        try:
            config = self.read_config()
            products = config.setdefault('products', {})
            if any(k != key and str(p.get('name', k)).strip().casefold() == name.casefold()
                   for k, p in products.items()):
                raise ValueError('已有同名类目，请使用不同的类目名称。')
            if key is None:
                key = 'category_' + uuid4().hex
                while key in products:
                    key = 'category_' + uuid4().hex
            product = deepcopy(products.get(key, self.product))
            product.update(name=name, target_fields=names,
                field_config={r['name']: r['rule'] for r in self.rows},
                vision_allowed_fields=[r['name'] for r in self.rows if r['vision']],
                vision_field_config={r['name']: r['vision_rule'] for r in self.rows},
                field_output={r['name']: {'language': r['language'], 'format': r['format']} for r in self.rows})
            products[key] = product
            fd, pending = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(self.config_path)), suffix='.json')
            with os.fdopen(fd, 'w', encoding='utf-8') as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
            os.replace(pending, self.config_path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '保存失败', str(exc))
            return
        finally:
            if pending and os.path.exists(pending):
                os.unlink(pending)
        self.dirty = False
        self.original_key = key
        self.hide()
        self.saved.emit(key)

    def cancel(self):
        if self.can_discard():
            self.dirty = False
            self.hide()
