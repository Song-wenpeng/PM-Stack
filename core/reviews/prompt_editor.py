"""View the actual extraction prompt and edit its category-specific instructions."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QPlainTextEdit, QLabel, QTabWidget, QWidget, QMessageBox,
)
from core.widgets import configure_combo, make_button
from .analysis_dialog import load_product_templates
from .category_editor import save_templates


def update_prompt(config_mgr, key, system, description, tasks, expected):
    source = Path(config_mgr.resolve_config("product_configs.json"))
    data = json.loads(source.read_text(encoding="utf-8"))
    products = data.get("products", data)
    if key not in products or products[key] != expected:
        raise ValueError("模板已在其他位置修改，请关闭后重新打开再编辑。")
    if not system.strip() or not description.strip() or not tasks:
        raise ValueError("系统角色、产品说明和分析任务均不能为空。")
    entry = copy.deepcopy(products[key])
    entry.update(system_prompt=system.strip(), product_desc=description.strip(), tasks=tasks)
    products[key] = entry
    save_templates(config_mgr, source, data)
    return entry


class PromptEditorDialog(QDialog):
    def __init__(self, config_mgr, parent=None, selected=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.templates = load_product_templates(config_mgr)
        self.current_key = None
        self.changed = False
        self.setWindowTitle("查看 / 修改提示词")
        self.resize(760, 660)
        layout = QVBoxLayout(self)
        intro = QLabel("按品类编辑评论标签提取提示词，保存后用于新的分析任务。已有任务继续使用创建时的模板。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.category = configure_combo(QComboBox())
        for key, entry in self.templates.items():
            self.category.addItem(entry.get("display_name", key), key)
        self.category.setCurrentIndex(max(0, self.category.findData(selected)))
        layout.addWidget(self.category)
        tabs = QTabWidget()
        edit_page = QWidget()
        form = QFormLayout(edit_page)
        self.system = QPlainTextEdit()
        self.system.setMaximumHeight(100)
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(100)
        self.tasks = QPlainTextEdit()
        form.addRow("系统角色", self.system)
        form.addRow("产品说明", self.description)
        form.addRow("分析任务\n（每行一项）", self.tasks)
        note = QLabel("输出字段和 JSON 格式由模板自动生成。修改任务时请保留对应字段名；新增维度可使用“新增品类”。")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(edit_page, "编辑提示词")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        tabs.addTab(self.preview, "完整提示词预览")
        layout.addWidget(tabs, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.reset_btn = make_button("还原未保存修改")
        self.reset_btn.clicked.connect(self._load)
        actions.addWidget(self.reset_btn)
        actions.addStretch()
        close = make_button("关闭")
        close.clicked.connect(self.reject)
        self.save_btn = make_button("保存提示词", "primary")
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(close)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)
        self.category.currentIndexChanged.connect(self._select)
        for editor in (self.system, self.description, self.tasks):
            editor.textChanged.connect(self._preview)
        self._load()

    def _draft(self):
        entry = copy.deepcopy(self.templates.get(self.current_key, {}))
        entry.update(system_prompt=self.system.toPlainText().strip(),
                     product_desc=self.description.toPlainText().strip(),
                     tasks=[line.strip() for line in self.tasks.toPlainText().splitlines() if line.strip()])
        return entry

    def _dirty(self):
        return self.current_key is not None and self._draft() != self.templates[self.current_key]

    def _discard(self):
        return not self._dirty() or QMessageBox.question(
            self, "尚未保存", "放弃当前未保存的提示词修改？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _select(self):
        if self._discard():
            self._load()
        else:
            self.category.blockSignals(True)
            self.category.setCurrentIndex(self.category.findData(self.current_key))
            self.category.blockSignals(False)

    def _load(self):
        self.current_key = self.category.currentData()
        entry = self.templates.get(self.current_key, {})
        for editor, value in ((self.system, entry.get("system_prompt", "")),
                              (self.description, entry.get("product_desc", "")),
                              (self.tasks, "\n".join(entry.get("tasks", [])))):
            editor.blockSignals(True)
            editor.setPlainText(value)
            editor.blockSignals(False)
        self.save_btn.setEnabled(bool(entry))
        self.status.setText("" if entry else "未找到分析模板，请先导入模板。")
        self._preview()

    def _preview(self):
        from scripts.comments_step_1_fast import build_prompt
        entry = self._draft()
        if not entry.get("fields"):
            self.preview.clear()
            return
        self.preview.setPlainText("【系统角色】\n" + entry["system_prompt"] +
                                  "\n\n【用户提示词】\n" + build_prompt(entry, "（运行时替换为实际评论正文）"))

    def _save(self):
        entry = self._draft()
        try:
            saved = update_prompt(self.config_mgr, self.current_key, entry["system_prompt"],
                                  entry["product_desc"], entry["tasks"], self.templates[self.current_key])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.status.setText(f"保存失败：{exc}")
            return
        self.templates[self.current_key] = saved
        self.changed = True
        self.status.setText("提示词已保存，原模板已自动备份。新的分析任务将使用此提示词。")

    def reject(self):
        if self._discard():
            super().reject()
